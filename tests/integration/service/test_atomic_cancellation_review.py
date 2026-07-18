from __future__ import annotations

from paperclaw.durability import SQLiteDurableServiceStore


def test_queued_cancellation_persists_state_reason_and_events_atomically(tmp_path):
    store = SQLiteDurableServiceStore(tmp_path / "queued-cancel.sqlite3")
    store.create_run("svc-queued", "digest")

    run, events = store.request_cancellation(
        "svc-queued",
        reason="user_requested",
    )

    assert run.state == "stopped"
    assert run.metadata["stop_reason"] == "user_requested"
    assert [event.event_type for event in events] == [
        "service.run.cancel_requested",
        "service.run.stopped",
    ]
    assert events[-1].terminal is True
    assert store.list_events("svc-queued") == events


def test_running_cancellation_keeps_lease_for_cooperative_stop(tmp_path):
    store = SQLiteDurableServiceStore(tmp_path / "running-cancel.sqlite3")
    store.create_run("svc-running", "digest")
    claimed = store.claim_next("worker-a", lease_seconds=30.0)
    assert claimed is not None

    run, events = store.request_cancellation(
        "svc-running",
        reason="user_requested",
    )

    assert run.state == "cancelling"
    assert run.metadata["stop_reason"] == "user_requested"
    assert [event.event_type for event in events] == [
        "service.run.cancel_requested"
    ]
    renewed = store.renew_lease(
        run.run_id,
        "worker-a",
        expected_run_version=run.version,
        lease_seconds=30.0,
    )
    assert renewed > run.updated_at
