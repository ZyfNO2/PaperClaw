from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.tasks import (
    SQLiteDurableTaskStore,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskOutputTool,
    TaskStopTool,
)
from paperclaw.tools.base import ToolContext, ToolValidationError


def test_task_tools_create_list_get_stop_and_output(tmp_path: Path) -> None:
    store = SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    context = ToolContext(tmp_path)
    create = TaskCreateTool(store)

    created = create.execute(
        {
            "task_id": "background-a",
            "objective": "analyze module a",
            "parent_run_id": "run-1",
            "acceptance_criteria": ["return summary"],
            "allowed_paths": ["src"],
            "writable_paths": [],
            "allowed_tools": ["file_read", "grep"],
            "idempotency_key": "same-request",
        },
        context,
    )
    replay = create.execute(
        {
            "task_id": "background-a",
            "objective": "analyze module a",
            "parent_run_id": "run-1",
            "acceptance_criteria": ["return summary"],
            "allowed_paths": ["src"],
            "writable_paths": [],
            "allowed_tools": ["file_read", "grep"],
            "idempotency_key": "same-request",
        },
        context,
    )

    assert json.loads(created.output)["created"] is True
    assert json.loads(replay.output)["created"] is False
    assert json.loads(TaskGetTool(store).execute({"task_id": "background-a"}, context).output)["task"]["status"] == "queued"
    listed = json.loads(
        TaskListTool(store).execute({"parent_run_id": "run-1"}, context).output
    )
    assert listed["count"] == 1

    stopped = json.loads(
        TaskStopTool(store).execute(
            {"task_id": "background-a", "reason": "user_requested"},
            context,
        ).output
    )
    assert stopped["task"]["status"] == "cancelled"
    output = json.loads(
        TaskOutputTool(store).execute({"task_id": "background-a"}, context).output
    )
    assert output["terminal"] is True
    assert output["events"][-1]["event_type"] == "task.cancelled"


def test_task_create_rejects_recursive_background_tool_access(tmp_path: Path) -> None:
    tool = TaskCreateTool(SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3"))
    with pytest.raises(ToolValidationError, match="recursive or unknown"):
        tool.validate(
            {
                "objective": "recursive",
                "allowed_tools": ["task_create"],
            }
        )
