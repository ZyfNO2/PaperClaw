"""Tool, schema, permission, extension-policy and duplicate-call metrics."""

from __future__ import annotations

import json
from typing import Any, Sequence

from paperclaw.trace import TraceEvent

from .contracts import EvaluationCase


def evaluate_tools(case: EvaluationCase, events: Sequence[TraceEvent]) -> dict[str, Any]:
    calls = [event for event in events if event.event_type == "tool.started"]
    names = [_tool(event) for event in calls]
    signatures = [f"{name}:{json.dumps(event.payload.get('arguments_digest', event.payload.get('call_index')), sort_keys=True)}" for name, event in zip(names, calls)]
    required = set(case.expectation.required_tools)
    allowed = set(case.expectation.allowed_tools)
    forbidden = set(case.expectation.forbidden_tools)
    validation_failures = [event for event in events if event.event_type in {"tool.failed", "permission.denied"} and str(event.error_code or event.payload.get("error_code", "")).upper() in {"VALIDATION_ERROR", "TOOL_VALIDATION_FAILED"}]
    schema_results = [event.payload.get("schema_valid") for event in calls if "schema_valid" in event.payload]
    denials = [event for event in events if event.event_type in {"tool.denied", "permission.denied"}]
    return {
        "required_tool_coverage": round(len(required & set(names)) / len(required), 6) if required else 1.0,
        "forbidden_tool_call_count": sum(name in forbidden for name in names),
        "unexpected_tool_call_count": sum(bool(allowed) and name not in allowed for name in names),
        "tool_schema_validation_rate": round(sum(value is True for value in schema_results) / len(calls), 6) if calls and len(schema_results) + len(validation_failures) == len(calls) else ("NOT_APPLICABLE" if not calls else "NOT_VERIFIED"),
        "invalid_argument_count": len(validation_failures) + sum(value is False for value in schema_results),
        "tool_failure_count": sum(event.event_type == "tool.failed" for event in events),
        "tool_timeout_count": sum(event.event_type == "tool.failed" and event.error_code in {"timeout", "extension_timeout"} for event in events),
        "duplicate_tool_call_count": _duplicate_calls(calls, signatures, events),
        "unnecessary_tool_call_count": 0,
        "tool_recovery_rate": _recovery_rate(events),
        "permission_denial_count": len(denials),
        "permission_bypass_count": sum(event.payload.get("permission_bypass") is True for event in events) + _denied_then_completed(events),
        "extension_policy_recheck_count": sum(event.payload.get("policy_rechecked") is True for event in calls),
        "tool_call_count": len(calls),
    }


def _recovery_rate(events: Sequence[TraceEvent]) -> float | str:
    failures = [event for event in events if event.event_type == "tool.failed"]
    if not failures:
        return "NOT_APPLICABLE"
    recovered = sum(any(later.sequence > event.sequence and later.event_type == "tool.completed" and _tool(later) == _tool(event) for later in events) for event in failures)
    return round(recovered / len(failures), 6)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _tool(event: TraceEvent) -> str:
    return _text(event.payload.get("tool")) or _text(event.payload.get("tool_name")) or "unknown"


def _denied_then_completed(events: Sequence[TraceEvent]) -> int:
    denied = [event for event in events if event.event_type in {"permission.denied", "tool.denied"}]
    return sum(any(later.sequence > event.sequence and later.event_type == "tool.completed" and _tool(later) == _tool(event) for later in events) for event in denied)


def _duplicate_calls(calls: Sequence[TraceEvent], signatures: Sequence[str], events: Sequence[TraceEvent]) -> int:
    duplicates = 0
    previous: dict[str, TraceEvent] = {}
    for call, signature in zip(calls, signatures):
        earlier = previous.get(signature)
        if earlier is not None and not any(earlier.sequence < event.sequence < call.sequence and event.event_type == "retry.scheduled" for event in events):
            duplicates += 1
        previous[signature] = call
    return duplicates


__all__ = ["evaluate_tools"]
