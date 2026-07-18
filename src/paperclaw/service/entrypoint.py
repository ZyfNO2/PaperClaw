"""Console entry point for the optional PaperClaw HTTP service."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from paperclaw.durability import SQLiteDurableServiceStore
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.tasks import (
    BackgroundTaskSupervisor,
    SQLiteDurableTaskStore,
    SubagentTaskExecutor,
    TaskApplicationService,
)
from paperclaw.tasks.bootstrap import TaskRuntimeComponents

from .fastapi_app import create_app
from .production_application import DurableRunApplicationService
from .resilience import TimeoutPolicy
from .runtime_factory import ServiceRuntimeFactory


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be numeric") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-active-runs", type=int, default=4)
    parser.add_argument("--max-active-tasks", type=int, default=4)
    parser.add_argument("--provider-task-concurrency", type=int, default=2)
    parser.add_argument("--lease-seconds", type=_positive_float, default=30.0)
    parser.add_argument("--heartbeat-seconds", type=_positive_float, default=5.0)
    parser.add_argument("--queue-timeout-seconds", type=_positive_float, default=300.0)
    parser.add_argument("--run-timeout-seconds", type=_positive_float, default=600.0)
    parser.add_argument(
        "--database",
        default=str(Path.home() / ".paperclaw" / "service.sqlite3"),
        help="SQLite durable service and task database path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_active_runs < 1:
        raise SystemExit("--max-active-runs must be positive")
    if args.max_active_tasks < 1:
        raise SystemExit("--max-active-tasks must be positive")
    if args.provider_task_concurrency < 1:
        raise SystemExit("--provider-task-concurrency must be positive")
    if args.heartbeat_seconds >= args.lease_seconds:
        raise SystemExit("--heartbeat-seconds must be less than --lease-seconds")
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional install
        raise RuntimeError(
            'Uvicorn is missing; install "paperclaw[service]"'
        ) from exc

    database_path = Path(args.database).expanduser()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    task_store = SQLiteDurableTaskStore(database_path)
    task_executor = SubagentTaskExecutor(
        lambda _agent_id: OpenAICompatibleModel.from_env(),
        enable_verification_gate=True,
    )
    task_supervisor = BackgroundTaskSupervisor(
        task_store,
        task_executor,
        worker_id="service-task-worker",
        max_concurrency=args.max_active_tasks,
        provider_concurrency=args.provider_task_concurrency,
        lease_seconds=args.lease_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    task_components = TaskRuntimeComponents(task_store, task_supervisor)
    task_service = TaskApplicationService(task_store, task_supervisor)
    task_service.recover()
    task_supervisor.start()

    runtime_factory = ServiceRuntimeFactory(task_runtime=task_components)
    run_store = SQLiteDurableServiceStore(database_path)
    service = DurableRunApplicationService(
        runtime_factory.create,
        run_store,
        max_active_runs=args.max_active_runs,
        lease_seconds=args.lease_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
        timeout_policy=TimeoutPolicy(
            queue_timeout_seconds=args.queue_timeout_seconds,
            run_timeout_seconds=args.run_timeout_seconds,
        ),
    )
    service.task_service = task_service

    app = create_app(service)
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        task_service.shutdown(wait=True)
        service.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
