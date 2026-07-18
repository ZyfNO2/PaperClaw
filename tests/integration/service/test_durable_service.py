from __future__ import annotations

from threading import Event
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from paperclaw.durability import SQLiteDurableServiceStore
from paperclaw.harness import ExecutionReport, QueryEngine
from paperclaw.service import DurableRunApplicationService, ServiceRunRequest
from paperclaw.service.resilience import TimeoutPolicy

ROOT = Path(__file__).parents[3]


class ImmediateExecutor:
    def execute(self, request, *, emit, stop_token):
        emit("model.completed", {"input_tokens": 3, "output_tokens": 2})
        return ExecutionReport(
            status="completed",
            output="durable-done",
            stop_reason="completed",
            model_calls=1,
            tool_calls=0,
        )


class BlockingExecutor:
    def __init__(self) -> None:
        self.entered = Event()

    def execute(self, request, *, emit, stop_token):
        self.entered.set()
        while not stop_token.is_cancelled:
            time.sleep(0.01)
        return ExecutionReport(
            status="stopped",
            output=None,
            stop_reason=stop_token.reason or "cancelled",
            model_calls=0,
            tool_calls=0,
        )


def engine_factory(executor):
    def create(request, event_handler):
        return QueryEngine(
            executor,
            conversation_id=request.conversation_id or "durable-test",
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


def test_durable_completion_idempotency_and_event_replay_survive_recreation(tmp_path):
    database = tmp_path / "service.sqlite3"
    request = ServiceRunRequest(
        task="do durable work",
        workspace=str(tmp_path),
        disconnect_policy="detach_on_disconnect",
    )
    first_store = SQLiteDurableServiceStore(database)
    first_service = DurableRunApplicationService(
        engine_factory(ImmediateExecutor()),
        first_store,
        max_active_runs=1,
        lease_seconds=1.0,
        heartbeat_seconds=0.1,
    )
    try:
        first = first_service.submit(request, idempotency_key="stable-key")
        terminal = wait_terminal(first_service, first.run.service_run_id)
        assert terminal.status == "completed"
        assert terminal.output == "durable-done"
        events_before = first_service.list_events(first.run.service_run_id)
        assert events_before
        assert [event.sequence for event in events_before] == list(
            range(1, len(events_before) + 1)
        )
    finally:
        first_service.shutdown()

    second_store = SQLiteDurableServiceStore(database)
    second_service = DurableRunApplicationService(
        engine_factory(ImmediateExecutor()),
        second_store,
        max_active_runs=1,
        lease_seconds=1.0,
        heartbeat_seconds=0.1,
    )
    try:
        replayed = second_service.list_events(first.run.service_run_id)
        assert replayed == events_before
        resumed = second_service.list_events(
            first.run.service_run_id,
            after_sequence=replayed[-2].sequence,
        )
        assert resumed == (replayed[-1],)
        duplicate = second_service.submit(request, idempotency_key="stable-key")
        assert duplicate.created is False
        assert duplicate.run.service_run_id == first.run.service_run_id
        assert duplicate.run.status == "completed"
    finally:
        second_service.shutdown()


def test_running_run_can_be_cancelled_through_durable_state(tmp_path):
    executor = BlockingExecutor()
    service = DurableRunApplicationService(
        engine_factory(executor),
        SQLiteDurableServiceStore(tmp_path / "cancel.sqlite3"),
        max_active_runs=1,
        lease_seconds=1.0,
        heartbeat_seconds=0.1,
    )
    try:
        run = service.submit(
            ServiceRunRequest(task="block", workspace=str(tmp_path))
        ).run
        assert executor.entered.wait(2.0)
        cancelling = service.cancel(run.service_run_id, reason="test_cancel")
        assert cancelling.status in {"cancelling", "stopped"}
        terminal = wait_terminal(service, run.service_run_id)
        assert terminal.status == "stopped"
        assert terminal.stop_reason == "test_cancel"
        event_types = [
            event.event_type for event in service.list_events(run.service_run_id)
        ]
        assert "service.run.cancel_requested" in event_types
    finally:
        service.shutdown()


def test_queue_timeout_has_layer_specific_error_code(tmp_path):
    now = [100.0]
    store = SQLiteDurableServiceStore(
        tmp_path / "timeout.sqlite3", clock=lambda: now[0]
    )
    request = ServiceRunRequest(task="late", workspace=str(tmp_path))
    run, created = store.create_run(
        "svc-timeout",
        request.digest(),
        metadata={
            "service_request": request.to_metadata(),
            "runtime_run_id": None,
            "stop_reason": None,
            "model_calls": 0,
            "tool_calls": 0,
            "output": None,
            "error": None,
        },
    )
    assert created is True
    now[0] = 200.0
    service = DurableRunApplicationService(
        engine_factory(ImmediateExecutor()),
        store,
        max_active_runs=1,
        lease_seconds=1.0,
        heartbeat_seconds=0.1,
        timeout_policy=TimeoutPolicy(queue_timeout_seconds=10.0),
        clock=lambda: now[0],
    )
    try:
        terminal = wait_terminal(service, run.run_id)
        assert terminal.status == "failed"
        assert terminal.stop_reason == "queue_timeout"
        assert terminal.error == {
            "code": "queue_timeout",
            "message": "run exceeded queue timeout before execution",
        }
    finally:
        service.shutdown()


def test_process_restart_reconciles_expired_lease_and_replays_events(tmp_path):
    database = tmp_path / "restart.sqlite3"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get(
        "PYTHONPATH", ""
    )
    create_script = f"""
import sqlite3
from paperclaw.durability import SQLiteDurableServiceStore
from paperclaw.service import ServiceRunRequest

path = {str(database)!r}
workspace = {str(tmp_path)!r}
store = SQLiteDurableServiceStore(path)
request = ServiceRunRequest(task="restart", workspace=workspace)
store.create_run(
    "svc-restart",
    request.digest(),
    metadata={{
        "service_request": request.to_metadata(),
        "runtime_run_id": None,
        "stop_reason": None,
        "model_calls": 0,
        "tool_calls": 0,
        "output": None,
        "error": None,
    }},
)
store.append_event(
    "svc-restart",
    "service.run.accepted",
    {{"source": "first-process"}},
)
store.claim_next("dead-worker", lease_seconds=60.0)
connection = sqlite3.connect(path)
connection.execute(
    "UPDATE durable_worker_leases SET expires_at = 0 WHERE run_id = ?",
    ("svc-restart",),
)
connection.commit()
connection.close()
"""
    subprocess.run(
        [sys.executable, "-c", create_script],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    recover_script = f"""
import json
from paperclaw.durability import RecoveryCoordinator, SQLiteDurableServiceStore

store = SQLiteDurableServiceStore({str(database)!r})
items = RecoveryCoordinator(store.run_store).reconcile()
run = store.get_run("svc-restart")
events = store.list_events("svc-restart")
print(json.dumps({{
    "state": run.state,
    "applied": [item.applied for item in items],
    "next_states": [item.next_state for item in items],
    "event_types": [event.event_type for event in events],
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", recover_script],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout.strip())
    assert payload == {
        "state": "queued",
        "applied": [True],
        "next_states": ["queued"],
        "event_types": ["service.run.accepted"],
    }
