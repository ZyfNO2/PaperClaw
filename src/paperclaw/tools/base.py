from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from paperclaw.harness.contracts import StopToken


@dataclass(frozen=True)
class ToolContext:
    """Execution context shared by every tool so path policy and output bounds stay consistent."""

    workspace: Path
    output_limit: int = 20_000
    stop_token: StopToken | None = None


@dataclass
class ToolResult:
    """Normalized tool outcome stored in history and reused by tests, CLI output, and later trace exporters."""

    ok: bool
    output: str
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolValidationError(ValueError):
    pass


class ToolControlFlow(RuntimeError):
    """Internal signal that must cross safe_execute without becoming a ToolResult.

    v0.05 uses this only for cooperative stop and hard call-budget exits at
    the tool boundary. It is not a user-facing tool failure and must never be
    swallowed as ``internal_error``.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Tool(Protocol):
    """Stable tool contract for registry lookup and flow-safe execution."""

    name: str
    description: str

    def validate(self, arguments: dict[str, Any]) -> None: ...
    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...


def require_string(arguments: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ToolValidationError(f"{key} must be a non-empty string")
    return value


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n...[truncated]", True


def safe_execute(tool: Tool, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
    """Convert tool failures to ToolResult while preserving runtime signals."""
    try:
        tool.validate(arguments)
        return tool.execute(arguments, context)
    except ToolControlFlow:
        raise
    except ToolValidationError as exc:
        return ToolResult(False, str(exc), "validation_error")
    except Exception as exc:  # defensive boundary: tools must not crash the flow
        return ToolResult(False, f"{type(exc).__name__}: {exc}", "internal_error")
