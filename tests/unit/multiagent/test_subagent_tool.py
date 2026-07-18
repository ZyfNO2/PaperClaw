from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.multiagent.contracts import (
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.coordinator import CoordinatorResult
from paperclaw.multiagent.tool import SubagentTaskTool
from paperclaw.tools.base import ToolContext, ToolValidationError


class FakeCoordinator:
    instances: list["FakeCoordinator"] = []

    def __init__(
        self,
        model_factory,
        workspace,
        *,
        budget,
        enable_verification_gate,
        event_handler,
    ) -> None:
        self.model_factory = model_factory
        self.workspace = Path(workspace)
        self.budget = budget
        self.enable_verification_gate = enable_verification_gate
        self.event_handler = event_handler
        self.goal = ""
        self.tasks = []
        self.cancelled: list[str] = []
        self.__class__.instances.append(self)

    def run(self, goal, tasks):
        self.goal = goal
        self.tasks = list(tasks)
        return CoordinatorResult(
            stop_reason=TeamStopReason.ALL_TASKS_COMPLETED,
            task_results={
                task.task_id: WorkerResult(
                    task_id=task.task_id,
                    status=WorkerStatus.COMPLETED,
                    summary=f"completed {task.title}",
                    changed_files=[f"{task.task_id}.txt"],
                    step_count=2,
                    model_call_count=1,
                    tool_call_count=1,
                )
                for task in tasks
            },
            summary="all delegated tasks completed",
        )

    def cancel(self, task_id, tasks):
        self.cancelled.append(task_id)


def _request() -> dict:
    return {
        "goal": "Inspect two independent areas",
        "max_agents": 2,
        "tasks": [
            {
                "task_id": "context",
                "title": "Inspect context runtime",
                "objective": "Read the context package and report boundaries.",
                "acceptance_criteria": ["List the relevant modules"],
                "allowed_paths": ["src/paperclaw/context"],
                "writable_paths": [],
                "allowed_tools": ["file_read", "grep"],
                "dependencies": [],
                "max_steps": 6,
            },
            {
                "task_id": "desktop",
                "title": "Inspect desktop runtime",
                "objective": "Read the desktop package and report boundaries.",
                "acceptance_criteria": ["List the relevant modules"],
                "allowed_paths": ["src/paperclaw/desktop"],
                "writable_paths": [],
                "allowed_tools": ["file_read", "grep"],
                "dependencies": [],
                "max_steps": 6,
            },
        ],
    }


def test_delegate_tasks_returns_compact_results_and_isolation_metadata(tmp_path) -> None:
    FakeCoordinator.instances.clear()
    tool = SubagentTaskTool(
        lambda agent_id: object(),
        coordinator_factory=FakeCoordinator,
    )

    result = tool.execute(_request(), ToolContext(tmp_path))

    assert result.ok is True
    assert result.error_code is None
    assert result.metadata == {
        "task_count": 2,
        "max_agents": 2,
        "context_isolation": "fresh_worker_state",
        "recursive_delegation": False,
        "result_truncated": False,
    }
    payload = json.loads(result.output)
    assert payload["stop_reason"] == "all_tasks_completed"
    assert set(payload["tasks"]) == {"context", "desktop"}
    assert payload["tasks"]["context"]["summary"] == "completed Inspect context runtime"

    coordinator = FakeCoordinator.instances[-1]
    assert coordinator.goal == "Inspect two independent areas"
    assert coordinator.budget.max_agents == 2
    assert coordinator.budget.max_total_steps == 12
    assert coordinator.tasks[0].allowed_tools == ["file_read", "grep"]


def test_delegate_tasks_rejects_recursive_tool_access() -> None:
    request = _request()
    request["tasks"][0]["allowed_tools"] = ["delegate_tasks"]
    tool = SubagentTaskTool(lambda agent_id: object())

    with pytest.raises(ToolValidationError, match="recursive tools"):
        tool.validate(request)


def test_delegate_tasks_rejects_unknown_dependency() -> None:
    request = _request()
    request["tasks"][1]["dependencies"] = ["missing-task"]
    tool = SubagentTaskTool(lambda agent_id: object())

    with pytest.raises(ToolValidationError, match="unknown dependencies"):
        tool.validate(request)


def test_delegate_tasks_rejects_unbounded_task_count() -> None:
    request = _request()
    request["tasks"] = request["tasks"] * 3
    for index, task in enumerate(request["tasks"]):
        task["task_id"] = f"task-{index}"
    tool = SubagentTaskTool(lambda agent_id: object())

    with pytest.raises(ToolValidationError, match="at most 4"):
        tool.validate(request)
