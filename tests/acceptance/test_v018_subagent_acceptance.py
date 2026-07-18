from __future__ import annotations

import json
from pathlib import Path
from threading import Barrier
from time import monotonic, sleep

from paperclaw.harness import RunLimits
from paperclaw.harness.agent_runtime_executor import _BudgetedTool, _Usage
from paperclaw.models.base import ModelTurn
from paperclaw.multiagent.budget_accounting import install_subagent_budget_accounting
from paperclaw.multiagent.contracts import AgentTask, TeamStopReason
from paperclaw.multiagent.coordinator import Coordinator
from paperclaw.multiagent.tool import SubagentTaskTool
from paperclaw.tools.base import ToolContext, ToolResult


class ScriptedModel:
    def __init__(self, responses: list[dict], barrier: Barrier | None = None) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []
        self._barrier = barrier
        self._barrier_used = False

    def complete(self, prompt: str) -> ModelTurn:
        self.prompts.append(prompt)
        if self._barrier is not None and not self._barrier_used:
            self._barrier_used = True
            self._barrier.wait(timeout=5)
            sleep(0.2)
        return ModelTurn(content=json.dumps(next(self._responses)))


def done(result: str) -> dict:
    return {
        "action": "done",
        "arguments": {
            "result": result,
            "verification": "read-only analysis completed",
            "remaining_issues": [],
        },
        "reason": "acceptance",
    }


def delegation_request() -> dict:
    return {
        "goal": "Analyze two unrelated modules",
        "max_agents": 2,
        "tasks": [
            {
                "task_id": "context",
                "title": "Analyze Context Compaction",
                "objective": "Analyze Context Compaction and summarize boundaries.",
                "acceptance_criteria": ["Return a compact module summary"],
                "allowed_paths": ["src/paperclaw/context"],
                "writable_paths": [],
                "allowed_tools": ["file_read", "grep"],
                "dependencies": [],
                "max_steps": 4,
            },
            {
                "task_id": "permissions",
                "title": "Analyze MCP permissions",
                "objective": "Analyze MCP permission boundaries and summarize risks.",
                "acceptance_criteria": ["Return a compact permission summary"],
                "allowed_paths": ["src/paperclaw/mcp"],
                "writable_paths": [],
                "allowed_tools": ["file_read", "grep"],
                "dependencies": [],
                "max_steps": 4,
            },
        ],
    }


def test_worker_prompts_receive_explicit_task_context_not_parent_transcript(
    tmp_path: Path,
) -> None:
    models: dict[str, ScriptedModel] = {}

    def factory(agent_id: str) -> ScriptedModel:
        model = ScriptedModel([done(agent_id)])
        models[agent_id] = model
        return model

    parent_private_transcript = "PARENT_PRIVATE_TRANSCRIPT_DO_NOT_COPY"
    tool = SubagentTaskTool(factory, enable_verification_gate=False)
    result = tool.execute(
        delegation_request(),
        ToolContext(tmp_path, remaining_model_calls=8, remaining_tool_calls=8),
    )

    assert result.ok is True
    assert models
    for model in models.values():
        assert model.prompts
        assert parent_private_transcript not in model.prompts[0]
        assert "acceptance" in model.prompts[0].lower()
    payload = json.loads(result.output)
    assert set(payload["tasks"]) == {"context", "permissions"}
    assert "history" not in payload


def test_independent_workers_reach_first_model_call_concurrently(tmp_path: Path) -> None:
    barrier = Barrier(2)

    def factory(agent_id: str) -> ScriptedModel:
        return ScriptedModel([done(agent_id)], barrier=barrier)

    tasks = [
        AgentTask(
            task_id="a",
            title="a",
            objective="analyze a",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["file_read"],
        ),
        AgentTask(
            task_id="b",
            title="b",
            objective="analyze b",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["file_read"],
        ),
    ]
    started = monotonic()
    result = Coordinator(
        factory,
        tmp_path,
        enable_verification_gate=False,
    ).run("parallel acceptance", tasks)
    elapsed = monotonic() - started

    assert result.stop_reason is TeamStopReason.ALL_TASKS_COMPLETED
    assert elapsed < 0.38


class NeverStopped:
    is_cancelled = False
    reason = None


class UsageProbeTool:
    name = "delegate_tasks"
    description = "usage probe"

    def __init__(self) -> None:
        self.context: ToolContext | None = None

    def validate(self, arguments):
        return None

    def execute(self, arguments, context):
        self.context = context
        return ToolResult(
            True,
            "ok",
            metadata={"child_model_calls": 2, "child_tool_calls": 3},
        )


def test_child_usage_is_added_to_parent_queryengine_budget(tmp_path: Path) -> None:
    install_subagent_budget_accounting()
    usage = _Usage(RunLimits(max_steps=10, max_model_calls=5, max_tool_calls=6))
    events: list[tuple[str, dict]] = []
    probe = UsageProbeTool()
    wrapped = _BudgetedTool(
        probe,
        usage,
        lambda name, payload: events.append((name, payload)) or len(events),
        NeverStopped(),
    )

    wrapped.validate({})
    result = wrapped.execute({}, ToolContext(tmp_path))

    assert result.ok is True
    assert probe.context is not None
    assert probe.context.remaining_model_calls == 5
    assert probe.context.remaining_tool_calls == 5
    assert usage.model_calls == 2
    assert usage.tool_calls == 4
    assert any(name == "subagent.usage_accounted" for name, _ in events)
