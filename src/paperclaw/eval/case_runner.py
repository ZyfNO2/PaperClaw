"""Evaluation case orchestration over existing runtime and Trace boundaries."""

from __future__ import annotations

from typing import Any, Sequence

from paperclaw.trace import TraceEvent

from .aggregate import evaluate_run_cost
from .contracts import CaseStatus, EvaluationCase, EvaluationFailure, EvaluationResult
from .gate_metrics import evaluate_gate
from .reliability_metrics import evaluate_reliability
from .runtime_adapter import RuntimeAdapter
from .tool_metrics import evaluate_tools
from .trace_validation import validate_evaluation_trace
from .workflow_metrics import evaluate_workflow


def run_case(case: EvaluationCase, adapter: RuntimeAdapter) -> EvaluationResult:
    try:
        execution = adapter.execute(case)
        events = execution.reader.get_run_trace(execution.run_id, require_terminal=False)
        groups = {
            "workflow": evaluate_workflow(case, events),
            "tools": evaluate_tools(case, events),
            "reliability": evaluate_reliability(case, events),
            "gate": evaluate_gate(case, events),
            "trace": validate_evaluation_trace(events),
            "aggregate": evaluate_run_cost(
                execution.reader,
                execution.run_id,
                require_terminal=False,
            ).to_dict(),
            "runtime": {"mode": case.mode, "trace_source": execution.trace_source, "classification": "offline control-flow evaluation" if case.mode == "offline" else case.mode},
        }
        observed_request_ids = {
            str(event.payload["request_id"])
            for event in events
            if isinstance(event.payload.get("request_id"), str)
        }
        groups["runtime"]["request_id_match"] = observed_request_ids == {str(case.request["request_id"])}
        failures = _failures(case, execution.run_id, events, groups)
        waiting = groups["gate"]["final_state_waiting_approval"] and not failures
        status = CaseStatus.WAITING_APPROVAL if waiting else (CaseStatus.FAIL if failures else CaseStatus.PASS)
        return EvaluationResult(case.case_id, case.digest(), execution.run_id, status, groups, failures, tuple(event.event_id for event in events))
    except Exception as exc:
        failure = EvaluationFailure("UNKNOWN", case.case_id, None, None, None, f"{type(exc).__name__}: {exc}")
        return EvaluationResult(case.case_id, case.digest(), None, CaseStatus.FAIL, {"runtime": {"mode": case.mode}}, (failure,))


def run_cases(cases: Sequence[EvaluationCase], adapter: RuntimeAdapter, *, fail_fast: bool = False) -> tuple[EvaluationResult, ...]:
    results = []
    for case in sorted(cases, key=lambda item: item.case_id):
        result = run_case(case, adapter)
        results.append(result)
        if fail_fast and result.status == CaseStatus.FAIL:
            break
    return tuple(results)


def _failures(case: EvaluationCase, run_id: str, events: Sequence[TraceEvent], groups: dict[str, dict[str, Any]]) -> tuple[EvaluationFailure, ...]:
    failures: list[EvaluationFailure] = []
    checks = [
        (not groups["trace"]["trace_complete"], "TRACE_INCOMPLETE", "Trace integrity rules failed"),
        (not groups["runtime"]["request_id_match"], "TRACE_INCOMPLETE", "Trace request_id did not match the Evaluation Case"),
        (not groups["workflow"]["terminal_state_match"], "WRONG_TERMINAL_STATE", "Terminal state did not match expectation"),
        (groups["workflow"]["required_role_coverage"] < 1, "ROLE_MISSING", "A required role was not observed"),
        (not groups["workflow"]["coordinator_assignment_valid"], "ASSIGNMENT_INVALID", "Coordinator assignment did not cover the Team Plan"),
        (groups["workflow"]["plan_task_coverage"] < 1 or groups["workflow"]["unfinished_task_count"] > 0, "WORKER_FAILED", "A Team Plan task was not completed"),
        (groups["workflow"]["completion_without_required_review"], "REVIEW_MISSING", "Completion occurred without required review"),
        (not groups["workflow"]["reviewer_decision_valid"], "REVIEW_REJECTED", "Reviewer decision was invalid"),
        (not groups["workflow"]["reviewer_rejection_followed_by_rework"], "REVIEW_REJECTED", "Reviewer rejection was not followed by rework"),
        (groups["workflow"]["review_loop_detected"], "REVIEW_LOOP", "Unchanged reviewer rejection loop detected"),
        (groups["workflow"]["step_limit_exceeded"], "STEP_LIMIT_EXCEEDED", "Case step limit exceeded"),
        (groups["workflow"]["required_output_coverage"] < 1, "WORKER_FAILED", "Required output fields were missing"),
        (groups["tools"]["forbidden_tool_call_count"] > 0, "TOOL_FORBIDDEN", "Forbidden Tool was called"),
        (groups["tools"]["required_tool_coverage"] < 1, "TOOL_NOT_ALLOWED", "A required Tool was not called"),
        (groups["tools"]["unexpected_tool_call_count"] > 0, "TOOL_NOT_ALLOWED", "Tool outside the allowlist was called"),
        (groups["tools"]["invalid_argument_count"] > 0, "TOOL_ARGUMENT_INVALID", "Tool arguments failed production-schema validation observation"),
        (groups["tools"]["tool_call_count"] > case.limits.max_tool_calls, "STEP_LIMIT_EXCEEDED", "Case Tool call limit exceeded"),
        (groups["tools"]["duplicate_tool_call_count"] > 0, "DUPLICATE_EXECUTION", "Duplicate Tool call detected without an observed retry"),
        (groups["tools"]["tool_timeout_count"] > 0, "TOOL_TIMEOUT", "Tool invocation timed out"),
        (groups["tools"]["tool_failure_count"] > 0 and groups["tools"]["tool_recovery_rate"] not in {1, 1.0}, "TOOL_FAILURE", "Tool failure did not recover"),
        (groups["tools"]["permission_bypass_count"] > 0, "PERMISSION_BYPASS", "Protected action bypassed permission policy"),
        (groups["reliability"]["retry_exhausted_count"] > 0, "RETRY_EXHAUSTED", "Retry budget was exhausted"),
        (groups["reliability"]["max_retries_exceeded"], "RETRY_EXHAUSTED", "Retry limit was exceeded"),
        (groups["reliability"]["repeated_error_loop_detected"], "REVIEW_LOOP", "Repeated unchanged error loop detected"),
        (groups["reliability"]["timeout_count"] > 0, "TIMEOUT", "Runtime timeout was observed"),
        (groups["reliability"]["duplicate_attempt_count"] > 0, "DUPLICATE_EXECUTION", "Duplicate successful attempt detected"),
        (not groups["reliability"]["ack_consistency"], "ACK_INCONSISTENT", "Ack did not correspond to one terminal result"),
        (groups["reliability"]["outbox_created"] > groups["reliability"]["outbox_delivered"], "OUTBOX_UNDELIVERED", "Outbox record was not delivered"),
        (groups["reliability"]["cancelled_work_after_cancel_count"] > 0, "CANCELLED", "Work continued after cancellation"),
        (not groups["reliability"]["terminal_state_consistency"], "WRONG_TERMINAL_STATE", "Conflicting terminal state detected"),
        (groups["gate"]["missing_gate"], "MISSING_GATE", "Expected HumanGate was not triggered"),
        (groups["gate"]["unexpected_gate"], "UNEXPECTED_GATE", "HumanGate blocked an unprotected action"),
        (not groups["gate"]["gate_reason_match"], "MISSING_GATE", "HumanGate reason did not match expectation"),
        (not groups["gate"]["gate_action_match"], "MISSING_GATE", "HumanGate action did not match expectation"),
        (groups["gate"]["protected_action_executed_before_approval"], "PROTECTED_ACTION_EXECUTED", "Protected action executed without approval"),
    ]
    for failed, code, message in checks:
        if failed:
            evidence = tuple(event.event_id for event in events[-3:])
            failures.append(EvaluationFailure(code, case.case_id, run_id, None, events[-1].sequence if events else None, message, evidence))
    return tuple(failures)


__all__ = ["run_case", "run_cases"]
