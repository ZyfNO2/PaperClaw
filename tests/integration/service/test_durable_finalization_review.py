from __future__ import annotations

from threading import Event
import time

import pytest

from paperclaw.durability import (
    LeaseConflictError,
    RecoveryCoordinator,
    SQLiteDurableServiceStore,
)
from paperclaw.harness import ExecutionReport, QueryEngine
from paperclaw.service import DurableRunApplicationService, ServiceRunRequest
from paperclaw.service.resilience import TimeoutPolicy


class ImmediateExecutor:
    def execute(self, request, *, emit, stop_token):
        return ExecutionReport(
            status="completed",
            output="done",
            stop_reason="completed",
            model_calls=1,
            tool_calls=0,
        )


class StopAwareExecutor:
    def execute(self, request, *, emit, stop_token):
        while not stop_token.is_cancelled:
            time.sleep(0.005)
        return ExecutionReport(
            status="stopped",
            output=None,
            stop_reason=stop_token.reason or "cancelled",
            model_calls=0,
            tool_calls=0,
        )


class BlockingFinalizeStore(SQLiteDurableServiceStore):
    def __init__(self, path):
        super().__init__(path)
        self.finalize_entered = Event()
        self.finalize_release = Event()

    def finalize_run(self, *args, **kwargs):
        if kwargs.get("event_type") == "service.run.finalized":
            self.finalize_entered.set()
            assert self.finalize_release.wait(3.0)
        return super().finalize_run(*args, **kwargs)


def engine_factory(executor):
    def create(request, event_handler):
        return QueryEngine(
            executor,
            conversation_id="review-test",
            event_handler=event_handler,
        )

    return create


def wait_terminal(service, run_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = service.get_run(run_id)
        if view.terminal:
            return view
        time.sleep(0.01)
    raise AssertionError(f"run did not become terminal: {run_id}")


def test_cancel_racing_with_result_finalization_is_not_runtime_failure(tmp_path):
    store = BlockingFinalizeStore(tmp_path / "cancel-finalize.sqlite3")
    service = DurableRunApplicationService(
        engine_factory(ImmediateExecutor()),
        store,
        max_active_runs=1,
        lease_seconds=1.0,
        heartbeat_seconds=0.1,
    )
    try:
        run = service.submit(
            ServiceRunRequest(task="race", workspace=str(tmp_path))
        ).run
        assert store.finalize_entered.wait(2.0)
        cancelling = service.cancel(run.service_run_id, reason="user_cancel")
        assert cancelling.status == "cancelling"
        store.finalize_release.set()
        terminal = wait_terminal(service, run.service_run_id)
        assert terminal.status == "stopped"
        assert terminal.stop_reason == "user_cancel"
        assert terminal.error is None
        finalized = [
            event
            for event in service.list_events(run.service_run_id)
            if event.event_type == "service.run.finalized"
        ]
        assert finalized[-1].payload["status"] == "stopped"
        assert not any(
            event.event_type == "service.run.failed"
            for event in service.list_events(run.service_run_id)
        )
    finally:
        store.finalize_release.set()
        service.shutdown()


def test_run_timeout_preserves_layer_specific_failure(tmp_path):
    service = DurableRunApplicationService(
        engine_factory(StopAwareExecutor()),
        SQLiteDurableServiceStore(tmp_path / "run-timeout.sqlite3"),
        max_active_runs=1,
        lease_seconds=1.0,
        heartbeat_seconds=0.1,
        timeout_policy=TimeoutPolicy(run_timeout_seconds=0.05),
    )
    try:
        run = service.submit(
            ServiceRunRequest(task="timeout", workspace=str(tmp_path))
        ).run
        terminal = wait_terminal(service, run.service_run_id)
        assert terminal.status == "failed"
        assert terminal.stop_reason == "run_timeout"
        assert terminal.error is not None
        assert terminal.error["code"] == "run_timeout"
    finally:
        service.shutdown()


def test_stale_worker_cannot_finalize_reclaimed_run(tmp_path):
    now = [100.0]
    store = SQLiteDurableServiceStore(
        tmp_path / "stale-worker.sqlite3", clock=lambda: now[0]
    )
    run, _ = store.create_run("svc-stale", "digest")
    claimed = store.claim_next("worker-a", lease_seconds=1.0)
    assert claimed is not None
    now[0] = 102.0
    reconciled = RecoveryCoordinator(store.run_store).reconcile()
    assert reconciled[0].next_state == "queued"
    claimed_again = store.claim_next("worker-b", lease_seconds=10.0)
    assert claimed_again is not None

    with pytest.raises(LeaseConflictError):
        store.finalize_run(
            run.run_id,
            worker_id="worker-a",
            requested_state="completed",
            stop_reason="completed",
            metadata_patch={"output": "stale"},
        )
    current = store.get_run(run.run_id)
    assert current.state == "running"
    assert current.metadata.get("output") != "stale"
