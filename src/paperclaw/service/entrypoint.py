"""Console entry point for the optional PaperClaw HTTP service."""

from __future__ import annotations

import argparse
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
from typing import Sequence

from .application import RunApplicationService
from .fastapi_app import create_app
=======
=======
>>>>>>> 70e7334
=======
>>>>>>> 77ef8ea
from pathlib import Path
from typing import Sequence

from paperclaw.durability import SQLiteDurableServiceStore

from .fastapi_app import create_app
from .production_application import DurableRunApplicationService
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> 18cf7be
from .runtime_factory import ServiceRuntimeFactory


=======
=======
>>>>>>> 77ef8ea
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


<<<<<<< HEAD
>>>>>>> 70e7334
=======
>>>>>>> 77ef8ea
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-active-runs", type=int, default=4)
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
=======
=======
=======
>>>>>>> 77ef8ea
    parser.add_argument("--lease-seconds", type=_positive_float, default=30.0)
    parser.add_argument("--heartbeat-seconds", type=_positive_float, default=5.0)
    parser.add_argument("--queue-timeout-seconds", type=_positive_float, default=300.0)
    parser.add_argument("--run-timeout-seconds", type=_positive_float, default=600.0)
<<<<<<< HEAD
>>>>>>> 70e7334
=======
>>>>>>> 77ef8ea
    parser.add_argument(
        "--database",
        default=str(Path.home() / ".paperclaw" / "service.sqlite3"),
        help="SQLite durable service database path",
    )
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
=======
>>>>>>> 77ef8ea
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_active_runs < 1:
        raise SystemExit("--max-active-runs must be positive")
<<<<<<< HEAD
<<<<<<< HEAD
=======
    if args.heartbeat_seconds >= args.lease_seconds:
        raise SystemExit("--heartbeat-seconds must be less than --lease-seconds")
>>>>>>> 70e7334
=======
    if args.heartbeat_seconds >= args.lease_seconds:
        raise SystemExit("--heartbeat-seconds must be less than --lease-seconds")
>>>>>>> 77ef8ea
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional install
        raise RuntimeError(
            'Uvicorn is missing; install "paperclaw[service]"'
        ) from exc

<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
    runtime_factory = ServiceRuntimeFactory()
    service = RunApplicationService(
        runtime_factory.create, max_active_runs=args.max_active_runs
=======
=======
>>>>>>> 70e7334
=======
>>>>>>> 77ef8ea
    database_path = Path(args.database).expanduser()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_factory = ServiceRuntimeFactory()
    store = SQLiteDurableServiceStore(database_path)
    service = DurableRunApplicationService(
        runtime_factory.create,
        store,
        max_active_runs=args.max_active_runs,
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
=======
>>>>>>> 77ef8ea
        lease_seconds=args.lease_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
        timeout_policy=TimeoutPolicy(
            queue_timeout_seconds=args.queue_timeout_seconds,
            run_timeout_seconds=args.run_timeout_seconds,
        ),
<<<<<<< HEAD
>>>>>>> 70e7334
=======
>>>>>>> 77ef8ea
    )
    app = create_app(service)
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        service.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
