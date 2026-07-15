"""Stable, versioned contracts for durable PaperClaw traces.

The trace layer is a read-side projection over the existing v0.04
``SessionEvent`` log.  It deliberately does not introduce a second event
store, a plugin manager, replay execution, or provider-specific behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

TRACE_SCHEMA_VERSION = 1

TERMINAL_EVENT_TYPES = frozenset(
    {
        "run.completed",
        "run.failed",
        "run.stopped",
        "run.cancelled",
        "flow.stopped",
    }
)


class TraceIntegrityError(ValueError):
    """Raised when a projected trace violates ordering or terminal rules."""


@dataclass(frozen=True)
class TraceEvent:
    """One redacted, JSON-safe event in a run trace.

    ``sequence`` remains the authoritative order.  ``occurred_at`` is useful
    for display and latency analysis but must never be used to reorder events.
    The payload is a redacted projection, not an archival copy of prompts,
    files, tool output, environment variables, or hidden model reasoning.
    """

    event_id: str
    sequence: int
    occurred_at: str
    conversation_id: str
    run_id: str
    event_type: str
    component: str
    status: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    duration_ms: int | None = None
    provider: str | None = None
    model: str | None = None
    error_code: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = TRACE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if self.schema_version != TRACE_SCHEMA_VERSION:
            raise TraceIntegrityError(
                f"unsupported trace schema_version={self.schema_version}"
            )
        if not self.event_id:
            raise TraceIntegrityError("event_id must not be empty")
        if self.sequence <= 0:
            raise TraceIntegrityError("sequence must be positive")
        if not self.occurred_at:
            raise TraceIntegrityError("occurred_at must not be empty")
        if not self.conversation_id:
            raise TraceIntegrityError("conversation_id must not be empty")
        if not self.run_id:
            raise TraceIntegrityError("run_id must not be empty")
        if not self.event_type:
            raise TraceIntegrityError("event_type must not be empty")
        if not self.component:
            raise TraceIntegrityError("component must not be empty")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise TraceIntegrityError("duration_ms must be non-negative")
        if not isinstance(self.payload, dict):
            raise TraceIntegrityError("payload must be a dict")


def validate_trace(
    events: Iterable[TraceEvent],
    *,
    require_terminal: bool = False,
) -> tuple[TraceEvent, ...]:
    """Validate a run trace and return an immutable snapshot.

    The function accepts an empty trace when ``require_terminal`` is false.
    A trace may contain at most one terminal event, and no event may follow it.
    This catches malformed imports and projection regressions even though the
    SQLite repository already enforces unique per-run sequences.
    """

    snapshot = tuple(events)
    previous_sequence = 0
    terminal_index: int | None = None
    run_id: str | None = None
    conversation_id: str | None = None

    for index, event in enumerate(snapshot):
        event.validate()
        if event.sequence <= previous_sequence:
            raise TraceIntegrityError(
                "trace sequences must be strictly increasing: "
                f"{event.sequence} after {previous_sequence}"
            )
        previous_sequence = event.sequence

        if run_id is None:
            run_id = event.run_id
            conversation_id = event.conversation_id
        elif event.run_id != run_id or event.conversation_id != conversation_id:
            raise TraceIntegrityError("a trace cannot mix runs or conversations")

        if event.event_type in TERMINAL_EVENT_TYPES:
            if terminal_index is not None:
                raise TraceIntegrityError("trace contains more than one terminal event")
            terminal_index = index
        elif terminal_index is not None:
            raise TraceIntegrityError("non-terminal event appears after terminal event")

    if require_terminal and terminal_index is None:
        raise TraceIntegrityError("trace does not contain a terminal event")
    return snapshot
