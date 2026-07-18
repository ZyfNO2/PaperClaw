"""Public contracts for the optional PaperClaw service layer."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from paperclaw.harness import RunLimits

ACTIVE_SERVICE_STATUSES = frozenset({"accepted", "running", "cancelling"})
TERMINAL_SERVICE_STATUSES = frozenset(
    {"completed", "failed", "blocked", "stopped", "budget_exhausted"}
)
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    }
)


class ServiceError(RuntimeError):
    """Base class for typed service-layer errors."""

    code = "service_error"
    status_code = 500


class RunNotFoundError(ServiceError):
    code = "run_not_found"
    status_code = 404


class IdempotencyConflictError(ServiceError):
    code = "idempotency_conflict"
    status_code = 409


class ConcurrencyLimitError(ServiceError):
    code = "concurrency_limit_reached"
    status_code = 429


class RunNotCancellableError(ServiceError):
    code = "run_not_cancellable"
    status_code = 409


class ServiceShuttingDownError(ServiceError):
    code = "service_shutting_down"
    status_code = 503


@dataclass(frozen=True)
class ServiceRunRequest:
    """Normalized service request passed to an injected QueryEngine factory."""

    task: str
    workspace: str
    limits: RunLimits = field(default_factory=RunLimits)
    conversation_id: str | None = None
    client_id: str | None = None
    enable_verification_gate: bool = True

    def __post_init__(self) -> None:
        task = self.task.strip()
        workspace = self.workspace.strip()
        if not task:
            raise ValueError("task must not be empty")
        if len(task) > 100_000:
            raise ValueError("task exceeds 100000 characters")
        if not workspace:
            raise ValueError("workspace must not be empty")
        normalized_workspace = str(Path(workspace).expanduser())
        conversation = _optional_identifier(self.conversation_id, "conversation_id")
        client = _optional_identifier(self.client_id, "client_id")
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "workspace", normalized_workspace)
        object.__setattr__(self, "conversation_id", conversation)
        object.__setattr__(self, "client_id", client)

    def digest(self) -> str:
        payload = {
            "task": self.task,
            "workspace": self.workspace,
            "conversation_id": self.conversation_id,
            "client_id": self.client_id,
            "enable_verification_gate": self.enable_verification_gate,
            "limits": {
                "max_steps": self.limits.max_steps,
                "max_model_calls": self.limits.max_model_calls,
                "max_tool_calls": self.limits.max_tool_calls,
            },
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PublicRunEvent:
    service_run_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    terminal: bool
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_run_id": self.service_run_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": sanitize_public(self.payload),
            "terminal": self.terminal,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class PublicRunView:
    service_run_id: str
    runtime_run_id: str | None
    status: str
    created_at: float
    updated_at: float
    last_event_sequence: int
    stop_reason: str | None
    model_calls: int
    tool_calls: int
    output: str | None
    error: Mapping[str, Any] | None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_SERVICE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_run_id": self.service_run_id,
            "runtime_run_id": self.runtime_run_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_event_sequence": self.last_event_sequence,
            "stop_reason": self.stop_reason,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "output": _bounded_text(self.output),
            "error": sanitize_public(self.error) if self.error else None,
            "terminal": self.terminal,
        }


@dataclass(frozen=True)
class SubmitOutcome:
    run: PublicRunView
    created: bool


def sanitize_public(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded JSON-safe value and drop secret-like fields."""

    if depth > 6:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:100]:
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            if normalized in _SECRET_KEYS or any(
                marker in normalized
                for marker in ("password", "secret", "api_key", "authorization")
            ):
                continue
            sanitized[key[:100]] = sanitize_public(raw_value, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_public(item, depth=depth + 1) for item in list(value)[:100]]
    return _bounded_text(str(value))


def _optional_identifier(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 128:
        raise ValueError(f"{name} exceeds 128 characters")
    if any(char.isspace() for char in normalized):
        raise ValueError(f"{name} must not contain whitespace")
    return normalized


def _bounded_text(value: str | None, limit: int = 20_000) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit] + "...<truncated>"
