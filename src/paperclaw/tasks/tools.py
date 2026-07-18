"""Agent-facing tools for durable task lifecycle operations."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import uuid4

from paperclaw.tools.base import (
    ToolContext,
    ToolResult,
    ToolValidationError,
    require_string,
    truncate,
)
from paperclaw.tools.registry import ToolRegistry

from .contracts import TaskSpec, TaskStatus
from .runtime import BackgroundTaskSupervisor
from .store import SQLiteDurableTaskStore

_ALLOWED_SUBAGENT_TOOLS = frozenset(
    {"file_read", "file_write", "file_edit", "grep", "bash"}
)


class TaskCreateTool:
    name = "task_create"
    description = (
        "Create a durable background Subagent task and return immediately. "
        "Arguments: objective, optional task_id, parent_run_id, dependencies, "
        "acceptance_criteria, allowed_paths, writable_paths, allowed_tools, "
        "max_steps, timeout_seconds, max_attempts, idempotency_key."
    )

    def __init__(
        self,
        store: SQLiteDurableTaskStore,
        supervisor: BackgroundTaskSupervisor | None = None,
    ) -> None:
        self._store = store
        self._supervisor = supervisor

    def validate(self, arguments: dict[str, Any]) -> None:
        _parse_create(arguments, workspace=".")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        spec = _parse_create(arguments, workspace=str(context.workspace))
        task, created = self._store.create_task(spec)
        if self._supervisor is not None:
            self._supervisor.start()
            self._supervisor.notify()
        return _json_result(
            {
                "created": created,
                "task": task.to_dict(),
                "execution": "background",
                "durable": True,
            },
            context.output_limit,
        )


class TaskGetTool:
    name = "task_get"
    description = "Get the durable state of one background task. Argument: task_id."

    def __init__(self, store: SQLiteDurableTaskStore) -> None:
        self._store = store

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "task_id")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        task = self._store.get_task(require_string(arguments, "task_id"))
        return _json_result({"task": task.to_dict()}, context.output_limit)


class TaskListTool:
    name = "task_list"
    description = (
        "List durable background tasks. Optional arguments: parent_run_id, "
        "statuses, limit."
    )

    def __init__(self, store: SQLiteDurableTaskStore) -> None:
        self._store = store

    def validate(self, arguments: dict[str, Any]) -> None:
        _parse_list(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        parent_run_id, statuses, limit = _parse_list(arguments)
        tasks = self._store.list_tasks(
            parent_run_id=parent_run_id,
            statuses=statuses,
            limit=limit,
        )
        return _json_result(
            {"tasks": [task.to_dict() for task in tasks], "count": len(tasks)},
            context.output_limit,
        )


class TaskStopTool:
    name = "task_stop"
    description = "Request cancellation of one durable task. Arguments: task_id, optional reason."

    def __init__(
        self,
        store: SQLiteDurableTaskStore,
        supervisor: BackgroundTaskSupervisor | None = None,
    ) -> None:
        self._store = store
        self._supervisor = supervisor

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "task_id")
        reason = arguments.get("reason", "user_requested")
        if not isinstance(reason, str) or not reason.strip():
            raise ToolValidationError("reason must be non-empty text")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        task = self._store.request_cancel(
            require_string(arguments, "task_id"),
            reason=str(arguments.get("reason", "user_requested")).strip(),
        )
        if self._supervisor is not None:
            self._supervisor.notify()
        return _json_result({"task": task.to_dict()}, context.output_limit)


class TaskOutputTool:
    name = "task_output"
    description = (
        "Read durable task output and events. Arguments: task_id, optional "
        "after_sequence and event_limit."
    )

    def __init__(self, store: SQLiteDurableTaskStore) -> None:
        self._store = store

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "task_id")
        _bounded_int(arguments.get("after_sequence", 0), "after_sequence", 0, 10**12)
        _bounded_int(arguments.get("event_limit", 200), "event_limit", 1, 5_000)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        task_id = require_string(arguments, "task_id")
        after = _bounded_int(
            arguments.get("after_sequence", 0),
            "after_sequence",
            0,
            10**12,
        )
        limit = _bounded_int(
            arguments.get("event_limit", 200),
            "event_limit",
            1,
            5_000,
        )
        task = self._store.get_task(task_id)
        events = self._store.list_events(
            task_id,
            after_sequence=after,
            limit=limit,
        )
        return _json_result(
            {
                "task_id": task_id,
                "status": task.status.value,
                "terminal": task.terminal,
                "output": task.output,
                "error": task.error,
                "stop_reason": task.stop_reason,
                "events": [event.to_dict() for event in events],
                "last_sequence": events[-1].sequence if events else after,
            },
            context.output_limit,
        )


def register_task_tools(
    registry: ToolRegistry,
    store: SQLiteDurableTaskStore,
    supervisor: BackgroundTaskSupervisor | None = None,
) -> None:
    for tool in (
        TaskCreateTool(store, supervisor),
        TaskGetTool(store),
        TaskListTool(store),
        TaskStopTool(store, supervisor),
        TaskOutputTool(store),
    ):
        if tool.name not in registry.names:
            registry.register(tool)


def _parse_create(arguments: Mapping[str, Any], *, workspace: str) -> TaskSpec:
    if not isinstance(arguments, Mapping):
        raise ToolValidationError("arguments must be an object")
    values = dict(arguments)
    objective = require_string(values, "objective").strip()
    task_id = values.get("task_id") or f"task-{uuid4().hex[:16]}"
    if not isinstance(task_id, str) or not task_id.strip():
        raise ToolValidationError("task_id must be non-empty text")
    parent_run_id = values.get("parent_run_id")
    if parent_run_id is not None and (
        not isinstance(parent_run_id, str) or not parent_run_id.strip()
    ):
        raise ToolValidationError("parent_run_id must be non-empty text")
    dependencies = _string_list(values.get("dependencies", []), "dependencies")
    acceptance = _string_list(
        values.get("acceptance_criteria", ["Return a structured task result."]),
        "acceptance_criteria",
    )
    allowed_paths = _string_list(values.get("allowed_paths", ["."]), "allowed_paths")
    writable_paths = _string_list(
        values.get("writable_paths", []),
        "writable_paths",
    )
    allowed_tools = _string_list(
        values.get("allowed_tools", ["file_read", "grep"]),
        "allowed_tools",
    )
    unknown = sorted(set(allowed_tools) - _ALLOWED_SUBAGENT_TOOLS)
    if unknown:
        raise ToolValidationError(
            "background Subagents cannot use recursive or unknown tools: "
            + ", ".join(unknown)
        )
    max_steps = _bounded_int(values.get("max_steps", 20), "max_steps", 1, 10_000)
    timeout = _positive_float(
        values.get("timeout_seconds", 600.0),
        "timeout_seconds",
        86_400.0,
    )
    max_attempts = _bounded_int(
        values.get("max_attempts", 2),
        "max_attempts",
        1,
        20,
    )
    idempotency_key = values.get("idempotency_key")
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str) or not idempotency_key.strip()
    ):
        raise ToolValidationError("idempotency_key must be non-empty text")
    metadata = {
        "title": str(values.get("title") or objective[:80]),
        "acceptance_criteria": acceptance,
        "allowed_paths": allowed_paths,
        "writable_paths": writable_paths,
        "allowed_tools": allowed_tools,
    }
    return TaskSpec(
        task_id=task_id.strip(),
        parent_run_id=parent_run_id.strip() if isinstance(parent_run_id, str) else None,
        objective=objective,
        workspace=workspace,
        dependencies=tuple(dependencies),
        max_steps=max_steps,
        timeout_seconds=timeout,
        max_attempts=max_attempts,
        idempotency_key=(
            idempotency_key.strip() if isinstance(idempotency_key, str) else None
        ),
        metadata=metadata,
    )


def _parse_list(
    arguments: Mapping[str, Any],
) -> tuple[str | None, list[TaskStatus] | None, int]:
    if not isinstance(arguments, Mapping):
        raise ToolValidationError("arguments must be an object")
    parent = arguments.get("parent_run_id")
    if parent is not None and (not isinstance(parent, str) or not parent.strip()):
        raise ToolValidationError("parent_run_id must be non-empty text")
    raw_statuses = arguments.get("statuses")
    statuses: list[TaskStatus] | None = None
    if raw_statuses is not None:
        names = _string_list(raw_statuses, "statuses")
        try:
            statuses = [TaskStatus(value) for value in names]
        except ValueError as exc:
            raise ToolValidationError("statuses contains an unknown task status") from exc
    limit = _bounded_int(arguments.get("limit", 200), "limit", 1, 1_000)
    return parent.strip() if isinstance(parent, str) else None, statuses, limit


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ToolValidationError(f"{name} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ToolValidationError(f"{name} must contain non-empty strings")
        result.append(item.strip())
    return result


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolValidationError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ToolValidationError(f"{name} must be within [{minimum}, {maximum}]")
    return value


def _positive_float(value: Any, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolValidationError(f"{name} must be numeric")
    normalized = float(value)
    if normalized <= 0 or normalized > maximum:
        raise ToolValidationError(f"{name} must be within (0, {maximum}]")
    return normalized


def _json_result(payload: dict[str, Any], limit: int) -> ToolResult:
    rendered, was_truncated = truncate(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        limit,
    )
    return ToolResult(
        True,
        rendered,
        metadata={"result_truncated": was_truncated},
    )


__all__ = [
    "TaskCreateTool",
    "TaskGetTool",
    "TaskListTool",
    "TaskOutputTool",
    "TaskStopTool",
    "register_task_tools",
]
