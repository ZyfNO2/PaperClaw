from __future__ import annotations

from threading import Event
import time

import pytest

from paperclaw.harness import ExecutionReport, QueryEngine
from paperclaw.service import (
    RunApplicationService,
    ServicePluginRegistry,
    ServiceRunRequest,
)
from paperclaw.service.contracts import (
    ConcurrencyLimitError,
    IdempotencyConflictError,
)


class ImmediateExecutor:
    def __init__(self, *, event_count: int = 1) -> None:
        self.event_count = event_count

    def execute(self, request, *, emit, stop_token):
        for index in range(self.event_count):
            emit(
                "model.completed",
                {
                    "index": index,
                    "api_key": "must-not-cross-boundary",
                    "authorization": "Bearer hidden",
                },
            )
        return ExecutionReport(
            status="completed",
            output="done",
            stop_reason="completed",
            model_calls=1,
            tool_calls=0,
        )


class BlockingExecutor:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def execute(self, request, *, emit, stop_token):
        self.entered.set()
        emit("tool.started", {"tool_name": "wait"})
        while not self.release.wait(0.01):
            if stop_token.is_cancelled:
                return ExecutionReport(
                    status="stopped",
                    output=None,
                    stop_reason=stop_token.reason or "cancelled",
                    model_calls=0,
                    tool_calls=1,
                )
        return ExecutionReport(
            status="completed",
            output="released",
            stop_reason="completed",
            model_calls=0,
            tool_calls=1,
        )


class FailingPlugin:
    plugin_id = "failing"

    def on_run_created(self, run):
        raise RuntimeError("created hook failed")

    def on_event(self, event):
        raise RuntimeError("event hook failed")

    def on_run_terminal(self, run):
        raise RuntimeError("terminal hook failed")


def engine_factory(executor):
    def create(request, event_handler):
        return QueryEngine(
            executor,
            conversation_id=request.conversation_id or "service-test",
            event_handler=event_handler,
        )

    return create


def wait_terminal(service, run_id, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = service.get_run(run_id)
        if view.terminal:
            return view
        time.sleep(0.01)
    raise AssertionError(f"run did not become terminal: {run_id}")


def test_completion_events_and_idempotency(tmp_path):
    service = RunApplicationService(engine_factory(ImmediateExecutor()))
    request = ServiceRunRequest(task="do work", workspace=str(tmp_path))
    try:
        first = service.submit(request, idempotency_key="same")
        second = service.submit(request, idempotency_key="same")
        assert first.created is True
        assert second.created is False
        assert second.run.service_run_id == first.run.service_run_id

        with pytest.raises(IdempotencyConflictError):
            service.submit(
                ServiceRunRequest(task="different", workspace=str(tmp_path)),
                idempotency_key="same",
            )

        terminal = wait_terminal(service, first.run.service_run_id)
        assert terminal.status == "completed"
        assert terminal.output == "done"
        events = service.list_events(first.run.service_run_id)
        assert [event.sequence for event in events] == sorted(
            event.sequence for event in events
        )
        assert sum(event.terminal for event in events) == 1
    finally:
        service.shutdown()


def test_cancel_and_global_concurrency_limit(tmp_path):
    executor = BlockingExecutor()
    service = RunApplicationService(
        engine_factory(executor), max_active_runs=1
    )
    request = ServiceRunRequest(task="wait", workspace=str(tmp_path))
    try:
        run = service.submit(request).run
        assert executor.entered.wait(1)
        with pytest.raises(ConcurrencyLimitError):
            service.submit(
                ServiceRunRequest(task="second", workspace=str(tmp_path))
            )
        cancelling = service.cancel(run.service_run_id)
        assert cancelling.status == "cancelling"
        terminal = wait_terminal(service, run.service_run_id)
        assert terminal.status == "stopped"
        assert terminal.stop_reason == "user_requested"
    finally:
        executor.release.set()
        service.shutdown()


def test_secret_fields_are_removed_and_plugin_failures_are_isolated(tmp_path):
    registry = ServicePluginRegistry([FailingPlugin()])
    service = RunApplicationService(
        engine_factory(ImmediateExecutor()), plugins=registry
    )
    try:
        run = service.submit(
            ServiceRunRequest(task="safe", workspace=str(tmp_path))
        ).run
        terminal = wait_terminal(service, run.service_run_id)
        assert terminal.status == "completed"
        serialized = repr(
            [event.to_dict() for event in service.list_events(run.service_run_id)]
        )
        assert "must-not-cross-boundary" not in serialized
        assert "Bearer hidden" not in serialized
        assert registry.failures
        assert {failure.hook for failure in registry.failures} >= {
            "on_run_created",
            "on_event",
            "on_run_terminal",
        }
    finally:
        service.shutdown()


def test_event_buffer_is_bounded_and_resume_uses_sequence(tmp_path):
    service = RunApplicationService(
        engine_factory(ImmediateExecutor(event_count=20)),
        event_capacity=8,
    )
    try:
        run = service.submit(
            ServiceRunRequest(task="many events", workspace=str(tmp_path))
        ).run
        terminal = wait_terminal(service, run.service_run_id)
        events = service.list_events(run.service_run_id)
        assert len(events) == 8
        assert events[-1].sequence == terminal.last_event_sequence
        resumed = service.list_events(
            run.service_run_id, after_sequence=events[-2].sequence
        )
        assert resumed == (events[-1],)
    finally:
        service.shutdown()
