"""Public contracts for durable background tasks and Subagent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class TaskStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    WAITING_DEPENDENCY = "waiting_dependency"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"
    UNKNOWN_OUTCOME = "unknown_outcome"


TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMED_OUT,
        TaskStatus.BLOCKED,
        TaskStatus.UNKNOWN_OUTCOME,
    }
)

ACTIVE_TASK_STATUSES = frozenset(
    {
        TaskStatus.CREATED,
        TaskStatus.QUEUED,
        TaskStatus.CLAIMED,
        TaskStatus.RUNNING,
        TaskStatus.WAITING_DEPENDENCY,
    }
)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    objective: str
    workspace: str
    parent_run_id: str | None = None
    dependencies: tuple[str, ...] = ()
    max_steps: int = 20
    timeout_seconds: float = 600.0
    max_attempts: int = 2
    idempotency_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    parent_run_id: str | None
    objective: str
    workspace: str
    status: TaskStatus
    version: int
    attempt: int
    max_attempts: int
    max_steps: int
    timeout_seconds: float
    cancel_requested: bool
    lease_owner: str | None
    lease_expires_at: float | None
    last_heartbeat_at: float | None
    side_effect_state: str
    created_at: float
    updated_at: float
    started_at: float | None
    completed_at: float | None
    stop_reason: str | None
    output: Mapping[str, Any] | None
    error: Mapping[str, Any] | None
    metadata: Mapping[str, Any]
    dependencies: tuple[str, ...] = ()

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_TASK_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_run_id": self.parent_run_id,
            "objective": self.objective,
            "workspace": self.workspace,
            "status": self.status.value,
            "version": self.version,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "max_steps": self.max_steps,
            "timeout_seconds": self.timeout_seconds,
            "cancel_requested": self.cancel_requested,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "side_effect_state": self.side_effect_state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stop_reason": self.stop_reason,
            "output": dict(self.output) if self.output is not None else None,
            "error": dict(self.error) if self.error is not None else None,
            "metadata": dict(self.metadata),
            "dependencies": list(self.dependencies),
            "terminal": self.terminal,
        }


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class TaskExecutionResult:
    status: TaskStatus
    output: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None
    stop_reason: str | None = None
    side_effect_state: str = "none"
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_TASK_STATUSES:
            raise ValueError("execution result status must be terminal")


class TaskRuntimeError(RuntimeError):
    pass


class TaskNotFoundError(TaskRuntimeError):
    pass


class TaskConflictError(TaskRuntimeError):
    pass


class TaskTransitionError(TaskRuntimeError):
    pass


class TaskLeaseError(TaskRuntimeError):
    pass


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "TaskConflictError",
    "TaskEvent",
    "TaskExecutionResult",
    "TaskLeaseError",
    "TaskNotFoundError",
    "TaskRecord",
    "TaskRuntimeError",
    "TaskSpec",
    "TaskStatus",
    "TaskTransitionError",
]
