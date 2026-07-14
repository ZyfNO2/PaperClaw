"""Phase A contract tests for the v0.05 QueryEngine skeleton."""

from __future__ import annotations

import threading

import pytest

from paperclaw.harness import ExecutionReport, QueryEngine, RunLimits


class StubExecutor:
    def __init__(self, report: ExecutionReport | None = None) -> None:
        self.report = report or ExecutionReport(
            status="completed",
            output="ok",
            stop_reason="completed",
            model_calls=1,
            tool_calls=1,
        )
        self.requests = []

    def execute(self, request, *, emit, stop_token):
        self.requests.append(request)
        emit("model.completed", {"model": "stub"})
        emit("tool.completed", {"tool": "stub"})
        return self.report


class RaisingExecutor:
    def execute(self, request, *, emit, stop_token):
        raise RuntimeError("boom")


class BlockingExecutor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.stop_seen = False

    def execute(self, request, *, emit, stop_token):
        self.started.set()
        self.release.wait(timeout=2)
        self.stop_seen = stop_token.is_cancelled
        return ExecutionReport(
            status="stopped" if self.stop_seen else "completed",
            output=None,
            stop_reason=stop_token.reason or "completed",
        )


def test_run_limits_require_positive_integers() -> None:
    with pytest.raises(ValueError):
        RunLimits(max_steps=0)
    with pytest.raises(ValueError):
        RunLimits(max_model_calls=True)


def test_submit_returns_structured_result_and_ordered_terminal_event() -> None:
    events: list[tuple[str, dict]] = []
    executor = StubExecutor()
    engine = QueryEngine(
        executor,
        conversation_id="conv-1",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )

    result = engine.submit("create hello.py", limits=RunLimits(3, 2, 2))

    assert result.status == "completed"
    assert result.output == "ok"
    assert result.model_calls == 1
    assert result.tool_calls == 1
    assert [payload["sequence"] for _, payload in events] == [1, 2, 3, 4]
    assert events[0][0] == "run.started"
    assert events[-1][0] == "run.completed"
    assert sum(
        event_type.startswith("run.")
        and event_type in {"run.completed", "run.failed", "run.stopped"}
        for event_type, _ in events
    ) == 1
    assert engine.get_run(result.run_id).last_event_sequence == 4
    assert executor.requests[0].limits.max_steps == 3


def test_executor_exception_is_normalized_to_failed_result() -> None:
    events: list[tuple[str, dict]] = []
    engine = QueryEngine(
        RaisingExecutor(),
        conversation_id="conv-1",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )

    result = engine.submit("fail")

    assert result.status == "failed"
    assert result.stop_reason == "executor_failed"
    assert events[-1][0] == "run.failed"
    assert events[-1][1]["error_code"] == "EXECUTOR_FAILED"


def test_executor_cannot_report_usage_above_limits() -> None:
    executor = StubExecutor(
        ExecutionReport(
            status="completed",
            output="invalid",
            stop_reason="completed",
            model_calls=3,
            tool_calls=0,
        )
    )
    engine = QueryEngine(executor, conversation_id="conv-1")

    result = engine.submit("bounded", limits=RunLimits(max_model_calls=2))

    assert result.status == "failed"
    assert result.stop_reason == "executor_contract_violation"


def test_request_stop_is_cooperative_and_idempotent() -> None:
    executor = BlockingExecutor()
    events: list[tuple[str, dict]] = []
    engine = QueryEngine(
        executor,
        conversation_id="conv-1",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )
    result_holder: list = []

    thread = threading.Thread(
        target=lambda: result_holder.append(engine.submit("long task")),
        daemon=True,
    )
    thread.start()
    assert executor.started.wait(timeout=1)
    run_id = events[0][1]["run_id"]

    assert engine.request_stop(run_id, "user_requested") is True
    assert engine.request_stop(run_id, "duplicate") is False
    executor.release.set()
    thread.join(timeout=2)

    assert result_holder[0].status == "stopped"
    assert result_holder[0].stop_reason == "user_requested"
    assert executor.stop_seen is True
    assert [event_type for event_type, _ in events].count("run.stop_requested") == 1
    assert events[-1][0] == "run.stopped"


def test_concurrent_submit_is_rejected() -> None:
    executor = BlockingExecutor()
    engine = QueryEngine(executor, conversation_id="conv-1")
    thread = threading.Thread(target=lambda: engine.submit("first"), daemon=True)
    thread.start()
    assert executor.started.wait(timeout=1)

    with pytest.raises(RuntimeError, match="concurrent submit"):
        engine.submit("second")

    executor.release.set()
    thread.join(timeout=2)


def test_unknown_run_is_explicit() -> None:
    engine = QueryEngine(StubExecutor(), conversation_id="conv-1")
    with pytest.raises(KeyError, match="unknown run_id"):
        engine.get_run("run-missing")
