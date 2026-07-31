"""Deterministic integrity checks over the existing durable TraceEvent contract."""

from __future__ import annotations

import json
from typing import Any, Sequence

from paperclaw.trace import TERMINAL_EVENT_TYPES, TraceEvent


def validate_evaluation_trace(events: Sequence[TraceEvent]) -> dict[str, Any]:
    starts = [event for event in events if event.event_type == "run.started"]
    terminals = [event for event in events if event.event_type in TERMINAL_EVENT_TYPES or event.event_type == "gate.waiting_approval"]
    calls: dict[str, TraceEvent] = {}
    results: set[str] = set()
    secret_risk = False
    for event in events:
        call_id = _call_key(event)
        if event.event_type == "tool.started" and call_id:
            calls[call_id] = event
        if event.event_type in {"tool.completed", "tool.failed", "tool.denied", "permission.denied"} and call_id:
            results.add(call_id)
        rendered = json.dumps(event.to_dict(), ensure_ascii=False).casefold()
        secret_risk |= any(marker in rendered for marker in ("api_key=", "bearer ", "secret://", "password="))
    unmatched_calls = sorted(set(calls) - results)
    monotonic = all(left.sequence < right.sequence for left, right in zip(events, events[1:]))
    terminal_index = next((index for index, event in enumerate(events) if event in terminals), None)
    after_terminal = bool(terminal_index is not None and terminal_index != len(events) - 1)
    return {
        "start_event_present": bool(starts),
        "terminal_event_present": bool(terminals),
        "terminal_event_count": len(terminals),
        "step_index_monotonic": monotonic,
        "unmatched_tool_call_count": len(unmatched_calls),
        "events_after_terminal_count": len(events) - terminal_index - 1 if after_terminal and terminal_index is not None else 0,
        "secret_exposure_detected": secret_risk,
        "trace_complete": bool(starts) and len(terminals) == 1 and monotonic and not unmatched_calls and not after_terminal and not secret_risk,
        "token_observation": "known" if any(event.event_type == "model.completed" and "total_tokens" in event.payload for event in events) else "unknown",
        "cost_observation": "known" if any(event.event_type == "model.completed" and "estimated_cost_usd" in event.payload for event in events) else "unknown",
    }


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _call_key(event: TraceEvent) -> str | None:
    explicit = _text(event.payload.get("call_id")) or event.span_id
    if explicit:
        return explicit
    tool = _text(event.payload.get("tool")) or _text(event.payload.get("tool_name"))
    index = event.payload.get("call_index", event.payload.get("step"))
    if tool and isinstance(index, int) and not isinstance(index, bool):
        return f"{tool}:{index}"
    return None


__all__ = ["validate_evaluation_trace"]
