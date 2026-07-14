from paperclaw.tui.bridge import TUIEventBridge


def test_bridge_merges_verification_into_monotonic_ui_sequence() -> None:
    events = []
    bridge = TUIEventBridge(lambda event_type, payload: events.append((event_type, payload)))

    bridge.handle_legacy_event("verification_completed", {"result": {"status": "early"}})
    bridge.handle_query_event(
        "run.started", {"run_id": "run-1", "sequence": 1, "status": "running"}
    )
    bridge.handle_query_event(
        "model.completed", {"run_id": "run-1", "sequence": 2, "call_index": 1}
    )
    bridge.handle_legacy_event(
        "verification_completed", {"result": {"status": "passed"}}
    )
    bridge.handle_query_event(
        "run.completed", {"run_id": "run-1", "sequence": 3, "status": "completed"}
    )

    assert [name for name, _ in events] == [
        "run.started",
        "model.completed",
        "verification.completed",
        "run.completed",
    ]
    assert [payload["sequence"] for _, payload in events] == [1, 2, 3, 4]
    assert events[-1][1]["query_sequence"] == 3


def test_bridge_drops_hidden_or_unmapped_legacy_events() -> None:
    events = []
    bridge = TUIEventBridge(lambda event_type, payload: events.append((event_type, payload)))
    bridge.handle_query_event("run.started", {"run_id": "run-1", "sequence": 1})
    bridge.handle_legacy_event("reasoning", {"reasoning": "secret"})
    assert [event_type for event_type, _ in events] == ["run.started"]
