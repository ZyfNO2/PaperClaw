"""Read-only summaries and timeline rendering for TraceEvent v1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .contracts import TERMINAL_EVENT_TYPES, TraceEvent
from .reader import TraceReader

_ERROR_SUFFIXES = (".failed", ".denied", ".blocked")
_SUMMARY_KEYS = (
    "tool",
    "error_code",
    "provider_error_code",
    "stop_reason",
    "finish_reason",
    "status_code",
    "retry_count",
    "request_id",
)


@dataclass(frozen=True)
class TimelineEntry:
    sequence: int
    occurred_at: str
    event_type: str
    component: str
    status: str | None
    duration_ms: int | None
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceInspection:
    run_id: str
    conversation_id: str
    event_count: int
    first_sequence: int | None
    last_sequence: int | None
    terminal_event: str | None
    terminal_status: str | None
    wall_duration_ms: int | None
    model_duration_ms: int
    tool_duration_ms: int
    model_calls: int
    tool_calls: int
    retry_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    error_count: int
    errors: tuple[TimelineEntry, ...]
    timeline: tuple[TimelineEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["errors"] = [entry.to_dict() for entry in self.errors]
        data["timeline"] = [entry.to_dict() for entry in self.timeline]
        return data


def inspect_run_trace(
    reader: TraceReader,
    run_id: str,
    *,
    require_terminal: bool = True,
    max_events: int | None = None,
) -> TraceInspection:
    if max_events is not None and max_events <= 0:
        raise ValueError("max_events must be positive")
    events = reader.get_run_trace(run_id, require_terminal=require_terminal)
    visible = events if max_events is None else events[:max_events]
    timeline = tuple(_entry(event) for event in visible)
    errors = tuple(entry for event, entry in zip(visible, timeline) if _is_error(event))
    terminal = next(
        (event for event in reversed(events) if event.event_type in TERMINAL_EVENT_TYPES),
        None,
    )

    model_calls = sum(event.event_type == "model.started" for event in events)
    tool_calls = sum(event.event_type == "tool.started" for event in events)
    model_duration_ms = sum(
        event.duration_ms or 0
        for event in events
        if event.component == "model"
        and event.event_type in {"model.completed", "model.failed"}
    )
    tool_duration_ms = sum(
        event.duration_ms or 0
        for event in events
        if event.component == "tool"
        and event.event_type in {"tool.completed", "tool.failed"}
    )
    retry_count = sum(
        _non_negative_int(event.payload.get("retry_count")) for event in events
    )
    input_tokens = sum(
        _non_negative_int(event.payload.get("input_tokens")) for event in events
    )
    output_tokens = sum(
        _non_negative_int(event.payload.get("output_tokens")) for event in events
    )
    total_tokens = sum(
        _non_negative_int(event.payload.get("total_tokens")) for event in events
    )

    return TraceInspection(
        run_id=events[0].run_id if events else run_id,
        conversation_id=events[0].conversation_id if events else "",
        event_count=len(events),
        first_sequence=events[0].sequence if events else None,
        last_sequence=events[-1].sequence if events else None,
        terminal_event=terminal.event_type if terminal else None,
        terminal_status=terminal.status if terminal else None,
        wall_duration_ms=_wall_duration(events),
        model_duration_ms=model_duration_ms,
        tool_duration_ms=tool_duration_ms,
        model_calls=model_calls,
        tool_calls=tool_calls,
        retry_count=retry_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        error_count=sum(_is_error(event) for event in events),
        errors=errors,
        timeline=timeline,
    )


def render_inspection_text(inspection: TraceInspection) -> str:
    lines = [
        f"Run: {inspection.run_id}",
        f"Conversation: {inspection.conversation_id or '-'}",
        (
            "Terminal: "
            f"{inspection.terminal_event or '-'} "
            f"({inspection.terminal_status or '-'})"
        ),
        (
            "Events: "
            f"{inspection.event_count} | model calls: {inspection.model_calls} | "
            f"tool calls: {inspection.tool_calls} | retries: {inspection.retry_count}"
        ),
        (
            "Duration(ms): "
            f"wall={_display(inspection.wall_duration_ms)} "
            f"model={inspection.model_duration_ms} "
            f"tool={inspection.tool_duration_ms}"
        ),
        (
            "Tokens: "
            f"input={inspection.input_tokens} "
            f"output={inspection.output_tokens} "
            f"total={inspection.total_tokens}"
        ),
        f"Errors: {inspection.error_count}",
        "",
        "Timeline:",
    ]
    for entry in inspection.timeline:
        status = f" [{entry.status}]" if entry.status else ""
        duration = (
            f" {entry.duration_ms}ms" if entry.duration_ms is not None else ""
        )
        summary = f" — {entry.summary}" if entry.summary else ""
        lines.append(
            f"{entry.sequence:>4} {entry.event_type}{status}{duration}{summary}"
        )
    if inspection.errors:
        lines.extend(["", "Error chain:"])
        for entry in inspection.errors:
            summary = entry.summary or entry.event_type
            lines.append(f"{entry.sequence:>4} {summary}")
    return "\n".join(lines)


def _entry(event: TraceEvent) -> TimelineEntry:
    summary_parts: list[str] = []
    if event.provider:
        summary_parts.append(f"provider={event.provider}")
    if event.model:
        summary_parts.append(f"model={event.model}")
    for key in _SUMMARY_KEYS:
        value = event.payload.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float, str)):
            text = str(value).strip()
            if text:
                summary_parts.append(f"{key}={text[:160]}")
    return TimelineEntry(
        sequence=event.sequence,
        occurred_at=event.occurred_at,
        event_type=event.event_type,
        component=event.component,
        status=event.status,
        duration_ms=event.duration_ms,
        summary=" ".join(summary_parts),
    )


def _is_error(event: TraceEvent) -> bool:
    return bool(
        event.error_code
        or event.event_type.endswith(_ERROR_SUFFIXES)
        or event.status in {"failed", "denied", "blocked"}
    )


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return 0


def _wall_duration(events: tuple[TraceEvent, ...]) -> int | None:
    if len(events) < 2:
        return None
    try:
        start = datetime.fromisoformat(events[0].occurred_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(events[-1].occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((end - start).total_seconds() * 1000))


def _display(value: int | None) -> str:
    return "-" if value is None else str(value)
