"""Runtime boundary tests for validation refusal and cooperative stop."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine
from paperclaw.models.base import ModelTurn
from paperclaw.tools.base import ToolContext, ToolResult, ToolValidationError
from paperclaw.tools.registry import ToolRegistry
from tests.helpers import FakeModel, action, done


class CountingTool:
    name = "count"
    description = "Count executions."

    def __init__(self) -> None:
        self.executions = 0

    def validate(self, arguments: dict) -> None:
        return None

    def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        self.executions += 1
        return ToolResult(True, "ok")


class RefusedTool(CountingTool):
    name = "refused"
    description = "Rejected by its existing validation rule."

    def validate(self, arguments: dict) -> None:
        raise ToolValidationError("operation denied by test validation")


class PausingModel:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, prompt: str) -> ModelTurn:
        self.started.set()
        self.release.wait(timeout=2)
        return ModelTurn(content=json.dumps(action("count", {})))


def test_validation_refusal_does_not_execute_tool(tmp_path: Path) -> None:
    tool = RefusedTool()
    events: list[tuple[str, dict]] = []
    model = FakeModel([action("refused", {}), done(result="handled")])
    engine = QueryEngine(
        AgentRuntimeExecutor(model, tmp_path, registry=ToolRegistry([tool])),
        conversation_id="conv-refused",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )

    result = engine.submit("try refused tool")

    assert result.status == "completed"
    assert result.tool_calls == 1
    assert tool.executions == 0
    assert any(event_type == "permission.denied" for event_type, _ in events)


def test_stop_request_prevents_following_tool_execution(tmp_path: Path) -> None:
    model = PausingModel()
    tool = CountingTool()
    events: list[tuple[str, dict]] = []
    engine = QueryEngine(
        AgentRuntimeExecutor(model, tmp_path, registry=ToolRegistry([tool])),
        conversation_id="conv-stop-real",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )
    results = []
    thread = threading.Thread(
        target=lambda: results.append(engine.submit("pause then stop")),
        daemon=True,
    )
    thread.start()
    assert model.started.wait(timeout=1)
    run_id = events[0][1]["run_id"]

    assert engine.request_stop(run_id, "user_requested") is True
    model.release.set()
    thread.join(timeout=2)

    assert results[0].status == "stopped"
    assert results[0].stop_reason == "user_requested"
    assert tool.executions == 0
