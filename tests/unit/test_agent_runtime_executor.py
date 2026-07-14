"""Phase B tests for the real AgentRuntime adapter."""

from __future__ import annotations

from pathlib import Path

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
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
    executor = AgentRuntimeExecutor(model, tmp_path, registry=ToolRegistry([tool]))
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
        AgentRuntimeExecutor(model, tmp_path, registry=ToolRegistry([tool])),
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
        AgentRuntimeExecutor(model, tmp_path, registry=ToolRegistry([tool])),
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
        AgentRuntimeExecutor(model, tmp_path, registry=ToolRegistry([tool])),
        conversation_id="conv-steps",
    )

    result = engine.submit(
        "one step",
        limits=RunLimits(max_steps=1, max_model_calls=3, max_tool_calls=3),
    )

    assert result.status == "budget_exhausted"
    assert result.stop_reason == "max_steps"
    assert tool.executions == 1
