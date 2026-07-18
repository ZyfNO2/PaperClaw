from __future__ import annotations

from threading import Event
import time

from paperclaw.durability import SQLiteDurableServiceStore
from paperclaw.harness import ExecutionReport, QueryEngine
from paperclaw.service import DurableRunApplicationService, ServiceRunRequest


class StopAwareExecutor:
    def execute(self, request, *, emit, stop_token):
        deadline = time.monotonic() + 2.0
        while not stop_token.is_cancelled and time.monotonic() < deadline:
            time.sleep(0.01)
        return ExecutionReport(
            status="stopped" if stop_token.is_cancelled else "failed",
            output=None,
            stop_reason=stop_token.reason or "stop_not_delivered",
            model_calls=0,
            tool_calls=0,
        )


class DelayedEngineFactory:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def __call__(self, request, event_handler):
        self.entered.set()
        assert self.release.wait(2.0)
        return QueryEngine(
            StopAwareExecutor(),
            conversation_id="cancel-race",
            event_handler=event_handler,
        )


def wait_terminal(service, run_id, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = service.get_run(run_id)
        if view.terminal:
            return view
        time.sleep(0.01)
    raise AssertionError("run did not become terminal")


def test_cancel_before_runtime_id_is_delivered_when_run_started_arrives(tmp_path):
    factory = DelayedEngineFactory()
    service = DurableRunApplicationService(
        factory,
        SQLiteDurableServiceStore(tmp_path / "cancel-race.sqlite3"),
        max_active_runs=1,
        lease_seconds=1.0,
        heartbeat_seconds=0.1,
    )
    try:
        run = service.submit(
            ServiceRunRequest(task="wait for runtime", workspace=str(tmp_path))
        ).run
        assert factory.entered.wait(2.0)
        cancelling = service.cancel(run.service_run_id, reason="cancel_before_runtime")
        assert cancelling.status == "cancelling"
        factory.release.set()
        terminal = wait_terminal(service, run.service_run_id)
        assert terminal.status == "stopped"
        assert terminal.stop_reason == "cancel_before_runtime"
    finally:
        factory.release.set()
        service.shutdown()
