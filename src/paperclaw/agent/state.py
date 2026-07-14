from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from paperclaw.tools.base import ToolResult


@dataclass
class ToolCall:
    action: str
    arguments: dict[str, Any]
    reason: str


@dataclass
class DoneAction:
    result: str
    verification: str = ""
    remaining_issues: list[str] = field(default_factory=list)


@dataclass
class HistoryEntry:
    step: int
    tool: str
    arguments: dict[str, Any]
    reason: str
    result: ToolResult

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def initial_state(task: str, workspace: Path, max_steps: int = 12) -> dict[str, Any]:
    return {
        "task": task,
        "workspace": workspace.resolve(strict=True),
        "history": [],
        "current_tool_call": None,
        "step_count": 0,
        "max_steps": max_steps,
        "invalid_output_count": 0,
        "result": None,
        "verification": None,
        "verification_status": "unverified",
        "remaining_issues": [],
        "stop_reason": None,
        "event_handler": None,
    }
