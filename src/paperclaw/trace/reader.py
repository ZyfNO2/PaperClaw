"""Read-side projection from durable SessionEvent records to TraceEvent v1."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, Protocol

from paperclaw.context.contracts import SessionEvent
from paperclaw.context.repository import Repository

from .contracts import TraceEvent, validate_trace
from .redaction import TraceRedactor


class TraceReader(Protocol):
    """Stable read boundary consumed by exporters and later plugins."""

    def get_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> tuple[TraceEvent, ...]: ...

    def iter_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> Iterator[TraceEvent]: ...


_COMPONENT_PREFIXES = {
    "run": "harness",
    "model": "model",
    "tool": "tool",
    "permission": "tool",
    "verification": "verification",
    "reflection": "reflection",
    "node": "runtime",
    "flow": "runtime",
    "context": "context",
    "checkpoint": "context",
}


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _duration_ms(payload: dict[str, Any]) -> int | None:
    for key in ("duration_ms", "latency_ms"):
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return int(round(value))
    return None


def _derive_component(event_type: str, payload: dict[str, Any]) -> str:
    explicit = _optional_text(payload.get("component"))
    if explicit:
        return explicit
    prefix = event_type.split(".", 1)[0].lower()
    return _COMPONENT_PREFIXES.get(prefix, "runtime")


def _derive_status(event_type: str, payload: dict[str, Any]) -> str | None:
    explicit = _optional_text(payload.get("status"))
    if explicit:
        return explicit
    suffix = event_type.rsplit(".", 1)[-1].lower()
    if suffix in {
        "started",
        "completed",
        "failed",
        "stopped",
        "cancelled",
        "denied",
        "blocked",
    }:
        return suffix
    return None


def project_session_event(
    event: SessionEvent,
    *,
    redactor: TraceRedactor | None = None,
) -> TraceEvent:
    """Project one durable SessionEvent without mutating the source payload."""

    sanitizer = redactor or TraceRedactor()
    payload = sanitizer.redact_payload(event.payload)
    trace = TraceEvent(
        event_id=event.event_id,
        sequence=event.sequence,
        occurred_at=event.created_at,
        conversation_id=event.conversation_id,
        run_id=event.run_id,
        event_type=event.event_type,
        component=_derive_component(event.event_type, payload),
        status=_derive_status(event.event_type, payload),
        span_id=_optional_text(payload.get("span_id")),
        parent_span_id=_optional_text(payload.get("parent_span_id")),
        duration_ms=_duration_ms(payload),
        provider=_optional_text(payload.get("provider")),
        model=_optional_text(payload.get("model")),
        error_code=_optional_text(payload.get("error_code")),
        payload=payload,
    )
    trace.validate()
    return trace


class RepositoryTraceReader:
    """TraceReader backed by the existing Repository event log.

    The reader never opens a write transaction and never creates a second
    persistence source.  Repository ordering remains authoritative.
    """

    def __init__(
        self,
        repository: Repository,
        *,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self._repository = repository
        self._redactor = redactor or TraceRedactor()

    def get_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> tuple[TraceEvent, ...]:
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        if since_sequence < 0:
            raise ValueError("since_sequence must be non-negative")
        events = (
            project_session_event(event, redactor=self._redactor)
            for event in self._repository.list_events(
                run_id,
                since_sequence=since_sequence,
            )
        )
        return validate_trace(events, require_terminal=require_terminal)

    def iter_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> Iterator[TraceEvent]:
        yield from self.get_run_trace(
            run_id,
            since_sequence=since_sequence,
            require_terminal=require_terminal,
        )


def project_events(
    events: Iterable[SessionEvent],
    *,
    redactor: TraceRedactor | None = None,
    require_terminal: bool = False,
) -> tuple[TraceEvent, ...]:
    """Project an in-memory event collection for tests and import tooling."""

    sanitizer = redactor or TraceRedactor()
    return validate_trace(
        (project_session_event(event, redactor=sanitizer) for event in events),
        require_terminal=require_terminal,
    )
