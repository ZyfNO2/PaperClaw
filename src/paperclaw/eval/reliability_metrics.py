"""At-least-once reliability and bounded-loop metrics from durable traces."""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from paperclaw.trace import TraceEvent

from .contracts import EvaluationCase


def evaluate_reliability(case: EvaluationCase, events: Sequence[TraceEvent]) -> dict[str, Any]:
    retries = [event for event in events if event.event_type == "retry.scheduled"]
    attempts = [event for event in events if event.event_type in {"task.started", "task.completed"}]
    successes = Counter(str(event.payload.get("task_id")) for event in attempts if event.event_type == "task.completed")
    outbox_created = sum(event.event_type == "outbox.created" for event in events)
    outbox_delivered = sum(event.event_type == "outbox.delivered" for event in events)
    cancelled_at = next((event.sequence for event in events if event.event_type in {"run.cancelled", "cancel.requested"}), None)
    after_cancel = sum(cancelled_at is not None and event.sequence > cancelled_at and event.event_type in {"task.started", "tool.started"} for event in events)
    terminal_count = sum(event.event_type in {"run.completed", "run.failed", "run.cancelled", "run.stopped", "gate.waiting_approval"} for event in events)
    errors = [str(event.error_code or event.payload.get("error_code") or "") for event in events if event.error_code or event.payload.get("error_code")]
    repeated_error = max(Counter(errors).values(), default=0)
    return {
        "retry_count": len(retries),
        "retry_success_rate": round(sum(_retry_recovered(retry, events) for retry in retries) / len(retries), 6) if retries else "NOT_APPLICABLE",
        "retry_exhausted_count": sum(event.event_type == "retry.exhausted" for event in events),
        "duplicate_attempt_count": sum(value - 1 for value in successes.values() if value > 1),
        "duplicate_side_effect_risk": sum(event.payload.get("duplicate_side_effect_risk") is True for event in events),
        "outbox_created": outbox_created,
        "outbox_delivered": outbox_delivered,
        "outbox_delivery_latency_ms": _duration(events, "outbox.delivered"),
        "ack_consistency": not any(event.event_type == "message.acked" for event in events) or terminal_count == 1,
        "terminal_state_consistency": terminal_count == 1,
        "dlq_count": sum(event.event_type in {"message.dead_lettered", "dlq.created"} for event in events),
        "cancelled_work_after_cancel_count": after_cancel,
        "recovered_claim_count": sum(event.event_type == "message.reclaimed" for event in events),
        "max_retries_exceeded": len(retries) > case.limits.max_retries,
        "repeated_error_loop_detected": repeated_error >= case.limits.loop_window,
        "timeout_count": sum(event.event_type in {"run.timeout", "task.timeout"} or event.status == "timeout" for event in events),
    }


def _duration(events: Sequence[TraceEvent], event_type: str) -> int | str:
    values = [event.duration_ms for event in events if event.event_type == event_type and event.duration_ms is not None]
    return sum(values) if values else "unknown"


def _retry_recovered(retry: TraceEvent, events: Sequence[TraceEvent]) -> bool:
    task_id = retry.payload.get("task_id")
    call_id = retry.payload.get("call_id")
    for later in events:
        if later.sequence <= retry.sequence or later.event_type not in {"task.completed", "tool.completed"}:
            continue
        if task_id is not None and later.payload.get("task_id") == task_id:
            return True
        if call_id is not None and later.payload.get("call_id") == call_id:
            return True
    return False


__all__ = ["evaluate_reliability"]
