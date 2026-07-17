"""Sanitized data contracts exposed by the desktop bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

_MAX_TASK_CHARS = 100_000
_MAX_RESULT_CHARS = 200_000
_MAX_PUBLIC_MESSAGE_CHARS = 500
_ALLOWED_REQUEST_FIELDS = frozenset(
    {
        "task",
        "workspace",
        "base_url",
        "api_key",
        "model",
        "provider",
        "enable_verification_gate",
        "max_steps",
        "max_model_calls",
        "max_tool_calls",
    }
)
_SECRET_FIELD_MARKERS = frozenset(
    {"api_key", "apikey", "authorization", "credential", "password", "secret", "token"}
)


class DesktopPublicError(ValueError):
    """Typed, bounded failure that is safe to return to JavaScript."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = str(code).strip().lower()
        normalized_message = _bounded_text(message, limit=_MAX_PUBLIC_MESSAGE_CHARS)
        if not normalized_code:
            raise ValueError("desktop error code must not be empty")
        if not normalized_message:
            raise ValueError("desktop error message must not be empty")
        super().__init__(normalized_message)
        self.code = normalized_code
        self.message = normalized_message

    def to_public_dict(self) -> dict[str, object]:
        return {"ok": False, "error_code": self.code, "error_message": self.message}


@dataclass(frozen=True)
class DesktopRunRequest:
    """Validated, run-scoped input. The API key is intentionally non-repr."""

    task: str
    workspace: str
    base_url: str
    api_key: str = field(repr=False)
    model: str
    provider: str = "openai-compatible"
    enable_verification_gate: bool = True
    max_steps: int = 12
    max_model_calls: int = 10
    max_tool_calls: int = 20

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DesktopRunRequest":
        if not isinstance(value, Mapping):
            raise DesktopPublicError("validation_error", "Run request must be an object.")
        unknown = sorted(str(key) for key in value.keys() if key not in _ALLOWED_REQUEST_FIELDS)
        if unknown:
            raise DesktopPublicError(
                "validation_error",
                f"Unknown request fields: {', '.join(unknown[:10])}.",
            )

        task = _required_text(value.get("task"), "Task", limit=_MAX_TASK_CHARS)
        workspace = _validate_workspace(value.get("workspace"))
        base_url = _validate_base_url(value.get("base_url"))
        api_key = _required_text(value.get("api_key"), "API key", limit=20_000)
        model = _required_text(value.get("model"), "Model", limit=256)
        provider = _required_text(
            value.get("provider", "openai-compatible"),
            "Provider",
            limit=128,
        )
        enable_verification_gate = _boolean(
            value.get("enable_verification_gate", True),
            "enable_verification_gate",
        )
        max_steps = _bounded_positive_int(value.get("max_steps", 12), "max_steps", 200)
        max_model_calls = _bounded_positive_int(
            value.get("max_model_calls", 10),
            "max_model_calls",
            100,
        )
        max_tool_calls = _bounded_positive_int(
            value.get("max_tool_calls", 20),
            "max_tool_calls",
            1_000,
        )
        return cls(
            task=task,
            workspace=workspace,
            base_url=base_url,
            api_key=api_key,
            model=model,
            provider=provider,
            enable_verification_gate=enable_verification_gate,
            max_steps=max_steps,
            max_model_calls=max_model_calls,
            max_tool_calls=max_tool_calls,
        )


@dataclass(frozen=True)
class DesktopRunSnapshot:
    run_id: str | None = None
    status: str = "idle"
    stop_reason: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    last_sequence: int = 0
    terminal: bool = False
    verification_status: str | None = None
    verification_summary: str | None = None
    final_result: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def to_public_dict(self, *, secret: str = "") -> dict[str, object]:
        return {
            "run_id": _optional_text(self.run_id, limit=128),
            "status": _bounded_text(self.status, limit=64) or "unknown",
            "stop_reason": _optional_text(self.stop_reason, secret=secret, limit=200),
            "model_calls": max(0, int(self.model_calls)),
            "tool_calls": max(0, int(self.tool_calls)),
            "last_sequence": max(0, int(self.last_sequence)),
            "terminal": bool(self.terminal),
            "verification_status": _optional_text(
                self.verification_status,
                secret=secret,
                limit=100,
            ),
            "verification_summary": _optional_text(
                self.verification_summary,
                secret=secret,
                limit=2_000,
            ),
            "final_result": _optional_text(
                self.final_result,
                secret=secret,
                limit=_MAX_RESULT_CHARS,
            ),
            "error_code": _optional_text(self.error_code, limit=100),
            "error_message": _optional_text(
                self.error_message,
                secret=secret,
                limit=_MAX_PUBLIC_MESSAGE_CHARS,
            ),
        }


@dataclass(frozen=True)
class DesktopEventRow:
    sequence: int
    event_type: str
    label: str
    tool: str | None = None
    call_index: int | None = None
    error_code: str | None = None
    terminal_reason: str | None = None
    verification_status: str | None = None

    def to_public_dict(self, *, secret: str = "") -> dict[str, object]:
        return {
            "sequence": max(0, int(self.sequence)),
            "event_type": _bounded_text(self.event_type, limit=100),
            "label": _bounded_text(self.label, secret=secret, limit=300),
            "tool": _optional_text(self.tool, secret=secret, limit=128),
            "call_index": self.call_index if _is_non_negative_int(self.call_index) else None,
            "error_code": _optional_text(self.error_code, limit=100),
            "terminal_reason": _optional_text(
                self.terminal_reason,
                secret=secret,
                limit=200,
            ),
            "verification_status": _optional_text(
                self.verification_status,
                secret=secret,
                limit=100,
            ),
        }


def public_event_row(event_type: str, payload: Mapping[str, Any]) -> DesktopEventRow:
    """Project an accepted runtime event through an explicit field allowlist."""

    sequence = payload.get("sequence")
    safe_sequence = sequence if _is_non_negative_int(sequence) else 0
    event_name = _bounded_text(event_type, limit=100) or "unknown.event"
    tool = None
    call_index = None
    error_code = None
    terminal_reason = None
    verification_status = None

    if event_name.startswith("model."):
        call_index = _optional_non_negative_int(payload.get("call_index"))
        error_code = _optional_text(payload.get("error_code"), limit=100)
    elif event_name.startswith("tool.") or event_name == "permission.denied":
        tool = _optional_text(payload.get("tool"), limit=128)
        call_index = _optional_non_negative_int(payload.get("call_index"))
        error_code = _optional_text(payload.get("error_code"), limit=100)
    elif event_name == "verification.completed":
        result = payload.get("result")
        result_map = result if isinstance(result, Mapping) else {}
        verification_status = _optional_text(
            result_map.get("status") or payload.get("status"),
            limit=100,
        )
    elif event_name.startswith("run."):
        terminal_reason = _optional_text(
            payload.get("stop_reason") or payload.get("reason"),
            limit=200,
        )
        error_code = _optional_text(payload.get("error_code"), limit=100)

    label_parts = [event_name]
    if tool:
        label_parts.append(f"tool={tool}")
    if call_index is not None:
        label_parts.append(f"call={call_index}")
    if error_code:
        label_parts.append(f"error={error_code}")
    if terminal_reason:
        label_parts.append(f"reason={terminal_reason}")
    if verification_status:
        label_parts.append(f"verification={verification_status}")
    return DesktopEventRow(
        sequence=safe_sequence,
        event_type=event_name,
        label=" · ".join(label_parts),
        tool=tool,
        call_index=call_index,
        error_code=error_code,
        terminal_reason=terminal_reason,
        verification_status=verification_status,
    )


def reject_secret_like_fields(value: Mapping[str, Any]) -> None:
    """Fail closed when a public payload attempts to expose a secret-shaped field."""

    for key in value:
        normalized = str(key).replace("-", "_").lower()
        if any(marker in normalized for marker in _SECRET_FIELD_MARKERS):
            raise DesktopPublicError(
                "runtime_error",
                "A protected field was rejected at the desktop boundary.",
            )


def sanitize_public_message(value: Any, *, secret: str = "", limit: int = 500) -> str:
    return _bounded_text(value, secret=secret, limit=limit)


def _validate_workspace(value: Any) -> str:
    raw = _required_text(value, "Workspace", limit=32_000)
    try:
        path = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DesktopPublicError(
            "workspace_not_found",
            "Workspace does not exist or cannot be opened.",
        ) from exc
    if not path.is_dir():
        raise DesktopPublicError(
            "workspace_not_found",
            "Workspace must be an existing directory.",
        )
    return str(path)


def _validate_base_url(value: Any) -> str:
    raw = _required_text(value, "Base URL", limit=2_000)
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DesktopPublicError(
            "provider_configuration_error",
            "Base URL must be an absolute HTTP or HTTPS URL.",
        )
    if parsed.username or parsed.password:
        raise DesktopPublicError(
            "provider_configuration_error",
            "Base URL must not contain embedded credentials.",
        )
    return raw.rstrip("/")


def _required_text(value: Any, label: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise DesktopPublicError("validation_error", f"{label} must be text.")
    normalized = value.strip()
    if not normalized:
        raise DesktopPublicError("validation_error", f"{label} must not be empty.")
    if len(normalized) > limit:
        raise DesktopPublicError("validation_error", f"{label} is too long.")
    return normalized


def _bounded_positive_int(value: Any, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise DesktopPublicError(
            "validation_error",
            f"{name} must be an integer in [1, {maximum}].",
        )
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise DesktopPublicError("validation_error", f"{name} must be a boolean.")
    return value


def _bounded_text(value: Any, *, secret: str = "", limit: int) -> str:
    if value is None:
        return ""
    text = str(value)
    if secret:
        text = text.replace(secret, "<REDACTED>")
    return text[:limit]


def _optional_text(
    value: Any,
    *,
    secret: str = "",
    limit: int,
) -> str | None:
    text = _bounded_text(value, secret=secret, limit=limit).strip()
    return text or None


def _is_non_negative_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _optional_non_negative_int(value: Any) -> int | None:
    return value if _is_non_negative_int(value) else None
