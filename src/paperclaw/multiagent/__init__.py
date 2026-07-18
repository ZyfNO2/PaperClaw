"""PaperClaw v0.03 MultiAgent runtime.

This package implements a small engineering-team execution model:
Coordinator, Worker, and independent Reviewer. It is intentionally
process-in-memory and does not claim crash recovery (that is v0.04).
"""

from __future__ import annotations

from paperclaw.multiagent.contracts import (
    AgentMessage,
    AgentRole,
    AgentTask,
    FileLease,
    LeaseDecision,
    MessageType,
    PermissionDecision,
    ReviewFinding,
    ReviewVerdict,
    TaskStatus,
    TeamBudget,
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.coordinator import Coordinator
from paperclaw.multiagent.events import EventEnvelope, emit_team_event
from paperclaw.multiagent.lease import LeaseManager
from paperclaw.multiagent.permissions import PermissionGuardLite
from paperclaw.multiagent.reviewer import Reviewer
from paperclaw.multiagent.tool import SubagentTaskTool
from paperclaw.multiagent.worker import Worker

__all__ = [
    "AgentMessage",
    "AgentRole",
    "AgentTask",
    "Coordinator",
    "EventEnvelope",
    "FileLease",
    "LeaseDecision",
    "LeaseManager",
    "MessageType",
    "PermissionDecision",
    "PermissionGuardLite",
    "ReviewFinding",
    "Reviewer",
    "ReviewVerdict",
    "SubagentTaskTool",
    "TaskStatus",
    "TeamBudget",
    "TeamStopReason",
    "Worker",
    "WorkerResult",
    "WorkerStatus",
    "emit_team_event",
]
