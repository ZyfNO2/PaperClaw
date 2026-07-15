"""Phase B tests for the real AgentRuntime adapter."""

from __future__ import annotations

import threading
from pathlib import Path

from paperclaw.context.repository import SQLiteRepository
from paperclaw.harness import (
    AgentRuntimeExecutor,
    ExecutionReport,
    QueryEngine,
    RunLimits,
    RunRequest,
)
from paperclaw.tools.base import ToolContext, ToolResult
from paperclaw.tools.registry import ToolRegistry
from tests.helpers import FakeModel, action, done


class RecordingTool:
    name = "record"
    description = "Record one deterministic test call."

    def __init__(self) -> None:
        self.executions = 0

    def validate(self, arguments: dict) -> None:
        return None

    def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        self.executions += 1
        return ToolResult(True, "recorded")


def test_real_adapter_completes_and_emits_model_tool_events(tmp_path: Path) -> None:
    tool = RecordingTool()
    events: list[tuple[str, dict]] = []
    model = FakeModel([action("record", {}), done(result="ok")])
    executor = AgentRuntimeExecutor(
        model,
        tmp_path,
        registry=ToolRegistry([tool]),
        enable_verification_gate=False,
    )
    engine = QueryEngine(
        executor,
        conversation_id="conv-real",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )

    result = engine.submit("record once")

    assert result.status == "completed"
    assert result.model_calls == 2
    assert result.tool_calls == 1
    assert tool.executions == 1
    event_names = [event_type for event_type, _ in events]
    assert "model.started" in event_names
    assert "model.completed" in event_names
    assert "tool.started" in event_names
    assert "tool.completed" in event_names
    assert events[-1][0] == "run.completed"


def test_model_budget_blocks_before_second_provider_call(tmp_path: Path) -> None:
    tool = RecordingTool()
    model = FakeModel([action("record", {}), done(result="not reached")])
    engine = QueryEngine(
        AgentRuntimeExecutor(
            model,
            tmp_path,
            registry=ToolRegistry([tool]),
            enable_verification_gate=False,
        ),
        conversation_id="conv-model-budget",
    )

    result = engine.submit(
        "bounded model",
        limits=RunLimits(max_steps=5, max_model_calls=1, max_tool_calls=5),
    )

    assert result.status == "budget_exhausted"
    assert result.stop_reason == "max_model_calls"
    assert result.model_calls == 1
    assert len(model.prompts) == 1
    assert tool.executions == 1


def test_tool_budget_blocks_before_second_tool_execution(tmp_path: Path) -> None:
    tool = RecordingTool()
    model = FakeModel(
        [
            action("record", {}, reason="first"),
            action("record", {}, reason="second"),
        ]
    )
    engine = QueryEngine(
        AgentRuntimeExecutor(
            model,
            tmp_path,
            registry=ToolRegistry([tool]),
            enable_verification_gate=False,
        ),
        conversation_id="conv-tool-budget",
    )

    result = engine.submit(
        "bounded tool",
        limits=RunLimits(max_steps=5, max_model_calls=5, max_tool_calls=1),
    )

    assert result.status == "budget_exhausted"
    assert result.stop_reason == "max_tool_calls"
    assert result.tool_calls == 1
    assert tool.executions == 1
    assert len(model.prompts) == 2


def test_max_steps_maps_to_budget_exhausted(tmp_path: Path) -> None:
    tool = RecordingTool()
    model = FakeModel([action("record", {})])
    engine = QueryEngine(
        AgentRuntimeExecutor(
            model,
            tmp_path,
            registry=ToolRegistry([tool]),
            enable_verification_gate=False,
        ),
        conversation_id="conv-steps",
    )

    result = engine.submit(
        "one step",
        limits=RunLimits(max_steps=1, max_model_calls=3, max_tool_calls=3),
    )

    assert result.status == "budget_exhausted"
    assert result.stop_reason == "max_steps"
    assert tool.executions == 1


def test_inflight_error_after_stop_maps_to_stopped(tmp_path: Path) -> None:
    """A provider-boundary failure racing with an accepted stop is stopped."""

    class FailingInflightModel:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def complete(self, prompt: str):
            self.started.set()
            assert self.release.wait(timeout=2)
            raise RuntimeError("provider call ended after cancellation")

    model = FailingInflightModel()
    events: list[tuple[str, dict]] = []
    engine = QueryEngine(
        AgentRuntimeExecutor(
            model,
            tmp_path,
            registry=ToolRegistry([]),
            enable_verification_gate=False,
        ),
        conversation_id="conv-stop-race",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )
    results = []
    thread = threading.Thread(
        target=lambda: results.append(engine.submit("wait then stop")),
        daemon=True,
    )

    thread.start()
    assert model.started.wait(timeout=1)
    run_id = events[0][1]["run_id"]
    assert engine.request_stop(run_id, "user_requested") is True
    model.release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert results[0].status == "stopped"
    assert results[0].stop_reason == "user_requested"
    assert results[0].model_calls == 1
    assert any(event == "model.failed" for event, _ in events)


def test_inflight_tool_execute_error_after_stop_maps_to_stopped(
    tmp_path: Path,
) -> None:
    """A tool-execution failure racing with an accepted stop is stopped."""

    class FailingInflightTool:
        name = "fail_inflight"
        description = "Block until released, then fail."

        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def validate(self, arguments: dict) -> None:
            return None

        def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
            self.started.set()
            assert self.release.wait(timeout=2)
            raise RuntimeError("tool execution ended after cancellation")

    tool = FailingInflightTool()
    events: list[tuple[str, dict]] = []
    engine = QueryEngine(
        AgentRuntimeExecutor(
            FakeModel([action("fail_inflight", {})]),
            tmp_path,
            registry=ToolRegistry([tool]),
            enable_verification_gate=False,
        ),
        conversation_id="conv-tool-stop-race",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )
    results = []
    thread = threading.Thread(
        target=lambda: results.append(engine.submit("run tool then stop")),
        daemon=True,
    )

    thread.start()
    assert tool.started.wait(timeout=1)
    run_id = next(
        payload["run_id"]
        for event_type, payload in events
        if event_type == "run.started"
    )
    assert engine.request_stop(run_id, "user_requested") is True
    tool.release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert len(results) == 1
    assert results[0].status == "stopped"
    assert results[0].stop_reason == "user_requested"
    assert results[0].tool_calls == 1
    assert any(
        event_type == "tool.failed"
        and payload.get("error_code") == "TOOL_EXECUTION_FAILED"
        for event_type, payload in events
    )
    terminal = [
        event_type
        for event_type, _ in events
        if event_type in {"run.completed", "run.failed", "run.stopped"}
    ]
    assert terminal == ["run.stopped"]


def test_runtime_failure_after_stop_is_not_hidden(tmp_path: Path, monkeypatch) -> None:
    """Catch-all runtime failures stay failed even when a token is cancelled."""

    class CancelledToken:
        is_cancelled = True
        reason = "user_requested"

    def fail_runtime(*args, **kwargs):
        raise RuntimeError("runtime boundary failed")

    monkeypatch.setattr("paperclaw.harness.agent_runtime_executor.AgentRuntime.run", fail_runtime)
    executor = AgentRuntimeExecutor(
        FakeModel([done(result="not reached")]),
        tmp_path,
        enable_verification_gate=False,
    )

    report = executor.execute(
        RunRequest(
            run_id="run-broken",
            conversation_id="conv-broken",
            text="fail",
            limits=RunLimits(),
        ),
        emit=lambda event, payload: 1,
        stop_token=CancelledToken(),
    )

    assert report.status == "failed"
    assert report.stop_reason == "runtime_failed"


def test_optional_session_binding_persists_messages_and_events(
    tmp_path: Path,
) -> None:
    repo = SQLiteRepository(tmp_path / "session.db", migrate=True)
    try:
        executor = AgentRuntimeExecutor(
            FakeModel([done(result="persisted")]),
            tmp_path,
            repository=repo,
            enable_verification_gate=False,
        )
        result = QueryEngine(
            executor,
            conversation_id="conv-session",
        ).submit("persist me")

        messages = repo.list_messages("conv-session")
        events = repo.list_events(result.run_id)
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert any(event.event_type == "model.started" for event in events)
        assert any(event.event_type == "flow.stopped" for event in events)
    finally:
        repo.close()


def test_recovery_required_is_preserved_as_blocked() -> None:
    class RecoveryExecutor:
        def execute(self, request, *, emit, stop_token):
            return ExecutionReport(
                status="blocked",
                output=None,
                stop_reason="recovery_required",
            )

    result = QueryEngine(
        RecoveryExecutor(),
        conversation_id="conv-recovery",
    ).submit("resume")

    assert result.status == "blocked"
    assert result.stop_reason == "recovery_required"
