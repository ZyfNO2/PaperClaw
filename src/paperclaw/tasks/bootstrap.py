"""Composition helpers for process-scoped durable task runtimes."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from paperclaw.models.base import ChatModel
from paperclaw.multiagent.judge_factory import build_judge_model_from_env

from .distributed_store import DurableTaskStore, FencedSQLiteDurableTaskStore
from .process_executor import SubprocessSubagentTaskExecutor
from .runtime import BackgroundTaskSupervisor
from .subagent import SubagentTaskExecutor
from .tools import register_task_tools


@dataclass(frozen=True)
class TaskRuntimeComponents:
    store: DurableTaskStore
    supervisor: BackgroundTaskSupervisor


_CACHE: dict[str, TaskRuntimeComponents] = {}
_CACHE_LOCK = RLock()
_CLI_MARKER = "_paperclaw_task_cli_extension"


def default_task_database() -> Path:
    configured = os.getenv("PAPERCLAW_TASK_DATABASE")
    path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".paperclaw" / "tasks.sqlite3"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_or_create_task_runtime(
    model_factory: Callable[[str], ChatModel],
    *,
    cache_key: str,
    database: str | Path | None = None,
    worker_id: str = "agent-task-worker",
    max_concurrency: int = 4,
    provider_concurrency: int = 2,
    judge_model_factory: Callable[[str], ChatModel] | None = None,
    executor_mode: str = "inprocess",
) -> TaskRuntimeComponents:
    resolved_database = Path(database or default_task_database()).expanduser().resolve()
    normalized_mode = _normalize_executor_mode(executor_mode)
    key = f"{resolved_database}:{cache_key}:{normalized_mode}"
    with _CACHE_LOCK:
        existing = _CACHE.get(key)
        if existing is not None:
            return existing
        # v0.25 production composition uses the fenced reference store. It is a
        # drop-in SQLite subclass for existing tools, while the runtime itself is
        # typed to the backend-neutral DurableTaskStore protocol.
        store = FencedSQLiteDurableTaskStore(resolved_database)
        if normalized_mode == "subprocess":
            executor = SubprocessSubagentTaskExecutor()
        else:
            executor = SubagentTaskExecutor(
                model_factory,
                judge_model_factory=judge_model_factory,
            )
        supervisor = BackgroundTaskSupervisor(
            store,
            executor,
            worker_id=worker_id,
            max_concurrency=max_concurrency,
            provider_concurrency=provider_concurrency,
        )
        store.recover_expired_leases()
        supervisor.start()
        components = TaskRuntimeComponents(store, supervisor)
        _CACHE[key] = components
        return components


def install_cli_task_extension(cli_module: Any) -> None:
    """Wrap CLI memory composition and register durable task tools once."""
    if getattr(cli_module, _CLI_MARKER, False):
        return
    original_build_memory_runtime = cli_module.build_memory_runtime

    def build_memory_runtime_with_tasks(*args: Any, **kwargs: Any):
        components = original_build_memory_runtime(*args, **kwargs)
        runtime = get_or_create_task_runtime(
            lambda _agent_id: cli_module.OpenAICompatibleModel.from_env(),
            judge_model_factory=lambda _agent_id: build_judge_model_from_env(),
            cache_key="cli-env",
            worker_id="cli-task-worker",
            executor_mode=os.getenv("PAPERCLAW_TASK_EXECUTOR_MODE", "inprocess"),
        )
        register_task_tools(
            components.tool_registry,
            runtime.store,  # type: ignore[arg-type] - protocol-compatible store
            runtime.supervisor,
        )
        return components

    cli_module.build_memory_runtime = build_memory_runtime_with_tasks
    setattr(cli_module, _CLI_MARKER, True)


def _normalize_executor_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"inprocess", "thread", "legacy"}:
        return "inprocess"
    if normalized in {"subprocess", "process"}:
        return "subprocess"
    raise ValueError("executor_mode must be inprocess or subprocess")


__all__ = [
    "TaskRuntimeComponents",
    "default_task_database",
    "get_or_create_task_runtime",
    "install_cli_task_extension",
]
