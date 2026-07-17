from paperclaw.desktop.event_queue import DesktopEventQueue


def test_event_queue_preserves_event_order_and_returns_copies() -> None:
    queue = DesktopEventQueue(max_items=5)
    source = {"sequence": 1, "label": "run.started"}
    queue.publish_event(source)
    source["label"] = "mutated"
    queue.publish_event({"sequence": 2, "label": "model.started"})

    items = queue.drain()
    assert [item["event"]["sequence"] for item in items] == [1, 2]
    assert items[0]["event"]["label"] == "run.started"
    items[0]["event"]["label"] = "consumer mutation"
    assert queue.size == 0


def test_snapshot_publish_coalesces_pending_snapshots() -> None:
    queue = DesktopEventQueue(max_items=5)
    queue.publish_event({"sequence": 1})
    queue.publish_snapshot({"status": "running", "last_sequence": 1})
    queue.publish_snapshot({"status": "completed", "last_sequence": 2})

    items = queue.drain()
    assert items == [
        {"kind": "event", "event": {"sequence": 1}},
        {
            "kind": "snapshot",
            "snapshot": {"status": "completed", "last_sequence": 2},
        },
    ]
    assert queue.dropped_count == 1


def test_queue_overflow_discards_oldest_without_blocking() -> None:
    queue = DesktopEventQueue(max_items=3)
    for sequence in range(1, 6):
        queue.publish_event({"sequence": sequence})

    assert queue.size == 3
    assert queue.dropped_count == 2
    assert [item["event"]["sequence"] for item in queue.drain()] == [3, 4, 5]


def test_drain_is_bounded_and_clear_resets_pending_items() -> None:
    queue = DesktopEventQueue(max_items=5)
    for sequence in range(1, 5):
        queue.publish_event({"sequence": sequence})
    assert len(queue.drain(limit=2)) == 2
    assert queue.size == 2
    queue.clear()
    assert queue.drain() == []
