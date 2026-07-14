from paperclaw.tui.state import EventReducer


def test_reducer_rejects_stale_and_post_terminal_events() -> None:
    reducer = EventReducer()
    assert reducer.apply("run.started", {"run_id": "run-1", "sequence": 1}).accepted
    assert reducer.apply(
        "model.started", {"run_id": "run-1", "sequence": 2, "call_index": 1}
    ).accepted
    stale = reducer.apply(
        "tool.started", {"run_id": "run-1", "sequence": 2, "call_index": 1}
    )
    assert stale.accepted is False
    terminal = reducer.apply(
        "run.completed",
        {
            "run_id": "run-1",
            "sequence": 3,
            "status": "completed",
            "stop_reason": "done",
            "model_calls": 1,
            "tool_calls": 0,
        },
    )
    assert terminal.snapshot.terminal is True
    after = reducer.apply("model.completed", {"run_id": "run-1", "sequence": 4})
    assert after.accepted is False
    assert after.snapshot.status == "completed"


def test_unknown_event_is_safe_and_does_not_render_payload() -> None:
    reducer = EventReducer()
    reducer.apply("run.started", {"run_id": "run-1", "sequence": 1})
    result = reducer.apply(
        "future.secret.event",
        {"run_id": "run-1", "sequence": 2, "reasoning": "do not render"},
    )
    assert result.accepted is True
    assert result.known_event is False
    assert "do not render" not in result.timeline_text
    assert "future.secret.event" in result.timeline_text
