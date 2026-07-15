from __future__ import annotations

import pytest

from paperclaw.replay import RecordedReplayError, replay_recorded_trace
from paperclaw.trace import TraceEvent


class _Reader:
    def __init__(self, events: tuple[TraceEvent, ...]) -> None:
        self.events = events

    def get_run_trace(self, run_id: str, **_kwargs) -> tuple[TraceEvent, ...]:
        assert run_id == "run-replay"
        return self.events

    def iter_run_trace(self, run_id: str, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


def _event(
    sequence: int,
    event_type: str,
    *,
    component: str,
    status: str | None = None,
    payload: dict | None = None,
) -> TraceEvent:
    return TraceEvent(
        event_id=f"evt-{sequence}",
        sequence=sequence,
        occurred_at=f"2026-07-16T00:00:0{sequence}+00:00",
        conversation_id="conv-replay",
        run_id="run-replay",
        event_type=event_type,
        component=component,
        status=status,
        payload=payload or {},
    )


def test_recorded_replay_applies_control_flow_without_dependencies() -> None:
    events = (
        _event(1, "run.started", component="harness", status="started"),
        _event(2, "model.started", component="model", payload={"call_index": 1}),
        _event(
            3,
            "model.completed",
            component="model",
            status="completed",
            payload={"call_index": 1, "retry_count": 1},
        ),
        _event(4, "tool.started", component="tool", payload={"call_index": 1}),
        _event(
            5,
            "tool.completed",
            component="tool",
            status="completed",
            payload={"call_index": 1},
        ),
        _event(6, "run.completed", component="harness", status="completed"),
    )

    result = replay_recorded_trace(_Reader(events), "run-replay", strict=True)

    assert result.faithful is True
    assert result.issue_count == 0
    assert result.applied_event_count == 6
    assert result.terminal_event == "run.completed"
    assert result.frames[-1].run_status == "completed"
    assert result.frames[-1].active_model_calls == 0
    assert result.frames[-1].active_tool_calls == 0
    assert result.frames[-1].retry_count == 1


def test_recorded_replay_detects_unmatched_call_end() -> None:
    events = (
        _event(1, "run.started", component="harness", status="started"),
        _event(
            2,
            "tool.completed",
            component="tool",
            status="completed",
            payload={"call_index": 9},
        ),
        _event(3, "run.completed", component="harness", status="completed"),
    )

    result = replay_recorded_trace(_Reader(events), "run-replay")
    assert result.faithful is False
    assert result.issues[0].code == "UNMATCHED_TOOL_CALL_END"

    with pytest.raises(RecordedReplayError, match="UNMATCHED_TOOL_CALL_END"):
        replay_recorded_trace(_Reader(events), "run-replay", strict=True)


@pytest.mark.parametrize(
    ("events", "issue_code"),
    [
        (
            (
                _event(1, "run.started", component="harness"),
                _event(2, "tool.started", component="tool", payload={"call_index": 1}),
                _event(3, "tool.started", component="tool", payload={"call_index": 1}),
                _event(4, "run.completed", component="harness"),
            ),
            "DUPLICATE_TOOL_CALL_START",
        ),
        (
            (
                _event(1, "run.started", component="harness"),
                _event(2, "tool.started", component="tool", payload={"call_index": 1}),
                _event(3, "run.completed", component="harness"),
            ),
            "TOOL_CALL_OPEN_AT_TERMINAL",
        ),
        (
            (
                _event(1, "run.started", component="harness"),
                _event(2, "run.completed", component="harness"),
                _event(3, "tool.completed", component="tool", payload={"call_index": 1}),
            ),
            "EVENT_AFTER_TERMINAL",
        ),
    ],
)
def test_recorded_replay_corruption_suite(
    events: tuple[TraceEvent, ...], issue_code: str
) -> None:
    result = replay_recorded_trace(_Reader(events), "run-replay")
    assert result.faithful is False
    assert issue_code in {issue.code for issue in result.issues}


def test_recorded_replay_is_deterministic() -> None:
    events = (
        _event(1, "run.started", component="harness", status="started"),
        _event(2, "run.completed", component="harness", status="completed"),
    )
    first = replay_recorded_trace(_Reader(events), "run-replay").to_dict()
    second = replay_recorded_trace(_Reader(events), "run-replay").to_dict()
    assert first == second
