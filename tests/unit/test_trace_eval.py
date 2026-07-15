from __future__ import annotations

from paperclaw.eval import EvalThresholds, evaluate_trace
from paperclaw.trace import TraceEvent


class _Reader:
    def __init__(self, events: tuple[TraceEvent, ...]) -> None:
        self.events = events

    def get_run_trace(self, run_id: str, **_kwargs) -> tuple[TraceEvent, ...]:
        assert run_id == "run-eval"
        return self.events

    def iter_run_trace(self, run_id: str, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


def _event(
    sequence: int,
    event_type: str,
    *,
    component: str,
    status: str | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    payload: dict | None = None,
) -> TraceEvent:
    return TraceEvent(
        event_id=f"evt-{sequence}",
        sequence=sequence,
        occurred_at=f"2026-07-16T00:00:0{sequence}+00:00",
        conversation_id="conv-eval",
        run_id="run-eval",
        event_type=event_type,
        component=component,
        status=status,
        duration_ms=duration_ms,
        error_code=error_code,
        payload=payload or {},
    )


def test_eval_scores_trace_and_applies_explicit_thresholds() -> None:
    events = (
        _event(1, "run.started", component="harness", status="started"),
        _event(2, "model.started", component="model", payload={"call_index": 1}),
        _event(
            3,
            "model.completed",
            component="model",
            status="completed",
            duration_ms=100,
            payload={
                "call_index": 1,
                "retry_count": 1,
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        ),
        _event(4, "tool.started", component="tool", payload={"call_index": 1}),
        _event(
            5,
            "tool.failed",
            component="tool",
            status="failed",
            error_code="EXIT_NONZERO",
            payload={"call_index": 1, "error_code": "EXIT_NONZERO"},
        ),
        _event(6, "run.completed", component="harness", status="completed"),
    )

    report = evaluate_trace(
        _Reader(events),
        "run-eval",
        thresholds=EvalThresholds(
            require_completed=True,
            max_retries=0,
            max_tool_failure_rate=0.5,
            max_errors=2,
        ),
    )

    metrics = {metric.name: metric for metric in report.metrics}
    assert report.overall_passed is False
    assert report.failed_checks == (
        "tool_failure_rate",
        "provider_retries",
    )
    assert metrics["terminal_completed"].passed is True
    assert metrics["recorded_replay_faithful"].passed is True
    assert metrics["tool_failure_rate"].value == 1.0
    assert metrics["tool_failure_rate"].passed is False
    assert metrics["provider_retries"].value == 1
    assert metrics["verification"].value == "not_recorded"
    assert metrics["total_tokens"].value == 15


def test_eval_threshold_boundaries_are_inclusive() -> None:
    events = (
        _event(1, "run.started", component="harness", status="started"),
        _event(2, "model.started", component="model", payload={"call_index": 1}),
        _event(
            3,
            "model.completed",
            component="model",
            status="completed",
            payload={"call_index": 1, "retry_count": 2},
        ),
        _event(4, "run.completed", component="harness", status="completed"),
    )
    at_limit = evaluate_trace(
        _Reader(events), "run-eval", thresholds=EvalThresholds(max_retries=2)
    )
    below_limit = evaluate_trace(
        _Reader(events), "run-eval", thresholds=EvalThresholds(max_retries=1)
    )
    assert at_limit.overall_passed is True
    assert below_limit.overall_passed is False
    assert below_limit.failed_checks == ("provider_retries",)
