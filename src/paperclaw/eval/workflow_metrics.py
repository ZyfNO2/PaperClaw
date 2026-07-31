"""Rule-based Team Plan and Coordinator/Worker/Reviewer trajectory metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from paperclaw.trace import TERMINAL_EVENT_TYPES, TraceEvent

from .contracts import EvaluationCase, VALID_ROLES


def evaluate_workflow(case: EvaluationCase, events: Sequence[TraceEvent]) -> dict[str, Any]:
    roles = {_field(event, "role") for event in events} - {None}
    task_ids = {_field(event, "task_id") for event in events if _field(event, "task_id")}
    plan_tasks = _plan_task_ids(case)
    assigned = {_field(event, "task_id") for event in events if event.event_type == "task.assigned"}
    completed = {_field(event, "task_id") for event in events if event.event_type == "task.completed"}
    reviews = [event for event in events if event.event_type == "review.completed"]
    verdicts = [_field(event, "verdict") for event in reviews]
    terminal = next((event for event in reversed(events) if event.event_type in TERMINAL_EVENT_TYPES or event.event_type == "gate.waiting_approval"), None)
    terminal_state = _terminal_state(terminal)
    expected = set(case.expectation.terminal_states)
    coverage = len(completed & plan_tasks) / len(plan_tasks) if plan_tasks else 1.0
    role_coverage = len(roles & set(case.expectation.required_roles)) / len(case.expectation.required_roles) if case.expectation.required_roles else 1.0
    required_review = "reviewer" in case.expectation.required_roles
    repeated_reject = _unchanged_review_loop(events)
    counts = Counter(_field(event, "task_id") for event in events if event.event_type == "task.assigned")
    observed_steps = [event.payload.get("step", event.payload.get("step_index")) for event in events]
    numeric_steps = [value for value in observed_steps if isinstance(value, int) and not isinstance(value, bool)]
    step_count = max(numeric_steps, default=sum(event.event_type in {"task.started", "model.started"} for event in events))
    outputs = [event.payload.get("output") for event in events if event.event_type in {"task.completed", "run.completed"} and isinstance(event.payload.get("output"), dict)]
    output_fields = set().union(*(set(item) for item in outputs)) if outputs else set()
    return {
        "terminal_state": terminal_state,
        "terminal_state_match": terminal_state in expected,
        "plan_task_coverage": round(coverage, 6),
        "required_role_coverage": round(role_coverage, 6),
        "unexpected_role_count": len(roles - VALID_ROLES),
        "coordinator_assignment_valid": (not plan_tasks or plan_tasks <= assigned) and not any(value > 1 for value in counts.values()),
        "worker_completion_rate": round(len(completed & (plan_tasks or task_ids)) / len(plan_tasks or task_ids), 6) if (plan_tasks or task_ids) else 1.0,
        "reviewer_invoked_when_required": not required_review or bool(reviews),
        "reviewer_decision_present": not required_review or all(verdicts),
        "reviewer_decision_valid": all(item in {"approve", "request_changes", "blocked"} for item in verdicts),
        "review_rework_count": sum(item == "request_changes" for item in verdicts),
        "reviewer_rejection_followed_by_rework": _reject_followed_by_rework(events),
        "reviewer_acceptance_followed_by_completion": _accept_followed_by_completion(events),
        "completion_without_required_review": required_review and terminal_state == "completed" and not reviews,
        "review_loop_detected": repeated_reject,
        "orphan_task_count": len((assigned | completed) - plan_tasks) if plan_tasks else 0,
        "unfinished_task_count": len(plan_tasks - completed),
        "step_limit_exceeded": step_count > case.limits.max_steps,
        "required_output_coverage": round(len(output_fields & set(case.expectation.required_output_fields)) / len(case.expectation.required_output_fields), 6) if case.expectation.required_output_fields else 1.0,
        "workflow_success": terminal_state in expected and coverage == 1.0 and role_coverage == 1.0 and not repeated_reject,
    }


def _plan_task_ids(case: EvaluationCase) -> set[str]:
    plan = case.plan or {}
    tasks = plan.get("tasks", ()) if isinstance(plan, dict) else ()
    return {str(item["task_id"]) for item in tasks if isinstance(item, dict) and item.get("task_id")}


def _field(event: TraceEvent, name: str) -> str | None:
    value = event.payload.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _terminal_state(event: TraceEvent | None) -> str | None:
    if event is None:
        return None
    if event.event_type == "gate.waiting_approval":
        return "waiting_approval"
    return {"run.completed": "completed", "run.failed": "failed", "run.cancelled": "cancelled", "run.stopped": event.status or "stopped"}.get(event.event_type, event.status)


def _reject_followed_by_rework(events: Sequence[TraceEvent]) -> bool:
    rejected = [event.sequence for event in events if event.event_type == "review.completed" and _field(event, "verdict") == "request_changes"]
    return not rejected or all(any(item.sequence > seq and item.event_type in {"task.assigned", "task.started"} for item in events) for seq in rejected)


def _accept_followed_by_completion(events: Sequence[TraceEvent]) -> bool:
    approved = [event.sequence for event in events if event.event_type == "review.completed" and _field(event, "verdict") == "approve"]
    return not approved or all(any(item.sequence > seq and item.event_type in {"task.completed", "run.completed"} for item in events) for seq in approved)


def _unchanged_review_loop(events: Sequence[TraceEvent]) -> bool:
    signatures = [(_field(event, "task_id"), _field(event, "input_digest")) for event in events if event.event_type == "review.completed" and _field(event, "verdict") == "request_changes"]
    return any(left == right for left, right in zip(signatures, signatures[1:]))


__all__ = ["evaluate_workflow"]
