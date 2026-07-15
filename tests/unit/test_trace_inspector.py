from __future__ import annotations

from paperclaw.trace import TraceEvent, inspect_run_trace, render_inspection_text


class _Reader:
    def __init__(self, events: tuple[TraceEvent, ...]) -> None:
        self.events = events

    def get_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> tuple[TraceEvent, ...]:
        assert run_id == "run-inspect"
        assert since_sequence == 0
        return self.events

    def iter_run_trace(self, *args, **kwargs):
        yield from self.get_run_trace(*args, **kwargs)


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
        conversation_id="conv-inspect",
        run_id="run-inspect",
        event_type=event_type,
        component=component,
        status=status,
        duration_ms=duration_ms,
        error_code=error_code,
        payload=payload or {},
    )


def test_inspector_aggregates_full_trace_but_bounds_timeline() -> None:
    events = (
        _event(1, "run.started", component="harness", status="started"),
        _event(
            2,
            "model.started",
            component="model",
            payload={"provider": "mistral", "model": "test-model"},
        ),
        _event(
            3,
            "model.completed",
            component="model",
            status="completed",
            duration_ms=120,
            payload={
                "retry_count": 1,
                "input_tokens": 10,
                "output_tokens": 4,
                "total_tokens": 14,
                "request_id": "req-1",
            },
        ),
        _event(4, "tool.started", component="tool", payload={"tool": "bash"}),
        _event(
            5,
            "tool.failed",
            component="tool",
            status="failed",
            duration_ms=25,
            error_code="EXIT_NONZERO",
            payload={"tool": "bash", "error_code": "EXIT_NONZERO"},
        ),
        _event(
            6,
            "run.failed",
            component="harness",
            status="failed",
            payload={"stop_reason": "runtime_failed"},
        ),
    )

    inspection = inspect_run_trace(
        _Reader(events),
        "run-inspect",
        max_events=3,
    )

    assert inspection.event_count == 6
    assert len(inspection.timeline) == 3
    assert inspection.model_calls == 1
    assert inspection.tool_calls == 1
    assert inspection.retry_count == 1
    assert inspection.model_duration_ms == 120
    assert inspection.tool_duration_ms == 25
    assert inspection.input_tokens == 10
    assert inspection.output_tokens == 4
    assert inspection.total_tokens == 14
    assert inspection.error_count == 2
    assert inspection.terminal_event == "run.failed"
    assert inspection.terminal_status == "failed"
    assert inspection.wall_duration_ms == 5000

    rendered = render_inspection_text(inspection)
    assert "model calls: 1" in rendered
    assert "tool calls: 1" in rendered
    assert "retries: 1" in rendered
    assert "Tokens: input=10 output=4 total=14" in rendered
    assert "request_id=req-1" in rendered


def test_inspector_handles_large_trace_without_truncating_aggregates() -> None:
    events = tuple(
        _event(
            sequence,
            "model.started" if sequence % 2 == 0 else "model.completed",
            component="model",
            duration_ms=1 if sequence % 2 else None,
        )
        for sequence in range(1, 10_001)
    )
    inspection = inspect_run_trace(
        _Reader(events),
        "run-inspect",
        require_terminal=False,
        max_events=25,
    )
    assert inspection.event_count == 10_000
    assert len(inspection.timeline) == 25
    assert inspection.model_calls == 5_000
    assert inspection.model_duration_ms == 5_000


def test_inspector_does_not_render_unapproved_payload_fields() -> None:
    event = _event(
        1,
        "model.failed",
        component="model",
        status="failed",
        payload={
            "prompt": "private paper text",
            "reasoning": "hidden chain",
            "tool_output": "private file",
            "authorization": "Bearer secret",
            "provider_error_code": "RATE_LIMITED",
        },
    )
    inspection = inspect_run_trace(
        _Reader((event,)),
        "run-inspect",
        require_terminal=False,
    )
    rendered = render_inspection_text(inspection)
    assert "RATE_LIMITED" in rendered
    for secret in ("private paper", "hidden chain", "private file", "Bearer"):
        assert secret not in rendered
