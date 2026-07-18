"""Stable contracts for local, subprocess, and future remote execution backends."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Mapping


class ExecutorStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    CRASHED = "crashed"
    UNKNOWN_OUTCOME = "unknown_outcome"


TERMINAL_EXECUTOR_STATUSES = frozenset(
    {
        ExecutorStatus.SUCCEEDED,
        ExecutorStatus.FAILED,
        ExecutorStatus.CANCELLED,
        ExecutorStatus.TIMED_OUT,
        ExecutorStatus.CRASHED,
        ExecutorStatus.UNKNOWN_OUTCOME,
    }
)


@dataclass(frozen=True)
class ExecutionRequest:
    execution_id: str
    task_id: str
    entrypoint: str
    payload: Mapping[str, Any]
    workspace: str
    timeout_seconds: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("execution_id", self.execution_id),
            ("task_id", self.task_id),
            ("entrypoint", self.entrypoint),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
            or self.timeout_seconds > 86_400
        ):
            raise ValueError("timeout_seconds must be in (0, 86400]")
        workspace = Path(self.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("workspace must resolve to an existing directory")
        object.__setattr__(self, "workspace", str(workspace))
        _ensure_json_object(self.payload, "payload")
        _ensure_json_object(self.metadata, "metadata")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["payload"] = dict(self.payload)
        data["metadata"] = dict(self.metadata)
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionRequest":
        return cls(
            execution_id=str(value.get("execution_id") or ""),
            task_id=str(value.get("task_id") or ""),
            entrypoint=str(value.get("entrypoint") or ""),
            payload=_mapping(value.get("payload")),
            workspace=str(value.get("workspace") or ""),
            timeout_seconds=float(value.get("timeout_seconds") or 0),
            metadata=_mapping(value.get("metadata")),
        )


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    task_id: str
    status: ExecutorStatus | str
    output: Mapping[str, Any] | None = None
    error_code: str | None = None
    error_type: str | None = None
    exit_code: int | None = None
    pid: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    termination_method: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = ExecutorStatus(self.status)
        if status not in TERMINAL_EXECUTOR_STATUSES:
            raise ValueError("execution result status must be terminal")
        object.__setattr__(self, "status", status)
        if self.output is not None:
            _ensure_json_object(self.output, "output")
        _ensure_json_object(self.metadata, "metadata")
        for name, value in (("error_code", self.error_code), ("error_type", self.error_type)):
            if value is not None and (not isinstance(value, str) or len(value) > 200):
                raise ValueError(f"{name} must be a bounded string or null")

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "output": dict(self.output) if self.output is not None else None,
            "error_code": self.error_code,
            "error_type": self.error_type,
            "exit_code": self.exit_code,
            "pid": self.pid,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "termination_method": self.termination_method,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionResult":
        output = value.get("output")
        return cls(
            execution_id=str(value.get("execution_id") or ""),
            task_id=str(value.get("task_id") or ""),
            status=str(value.get("status") or ""),
            output=_mapping(output) if output is not None else None,
            error_code=_optional_string(value.get("error_code")),
            error_type=_optional_string(value.get("error_type")),
            exit_code=_optional_int(value.get("exit_code")),
            pid=_optional_int(value.get("pid")),
            started_at=_optional_float(value.get("started_at")),
            finished_at=_optional_float(value.get("finished_at")),
            termination_method=_optional_string(value.get("termination_method")),
            metadata=_mapping(value.get("metadata")),
        )


def _ensure_json_object(value: Mapping[str, Any], name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-serializable") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{name} must serialize to a JSON object")


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutorStatus",
    "TERMINAL_EXECUTOR_STATUSES",
]
