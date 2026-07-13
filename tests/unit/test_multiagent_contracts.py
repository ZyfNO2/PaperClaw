"""Tests for v0.03 MultiAgent data contracts."""

from __future__ import annotations

from paperclaw.multiagent.contracts import (
    AgentMessage,
    AgentRole,
    AgentTask,
    FileLease,
    MessageType,
    ReviewFinding,
    ReviewVerdict,
    TaskStatus,
    TeamBudget,
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)


def test_task_status_enum_values():
    assert TaskStatus.READY.value == "ready"
    assert TaskStatus.RUNNING.value == "running"


def test_worker_result_serializes_status():
    result = WorkerResult(
        task_id="t1",
        status=WorkerStatus.COMPLETED,
        summary="done",
    )
    data = result.to_dict()
    assert data["status"] == "completed"
    assert data["task_id"] == "t1"


def test_agent_message_serializes_message_type():
    msg = AgentMessage(
        message_id="m1",
        sender_id="coordinator",
        recipient_id="worker-0",
        message_type=MessageType.TASK_ASSIGNED,
        task_id="t1",
    )
    data = msg.to_dict()
    assert data["message_type"] == "task.assigned"
    assert "timestamp" in data


def test_team_budget_defaults():
    budget = TeamBudget()
    assert budget.max_agents == 3
    assert budget.max_fix_rounds == 2


def test_review_finding_to_dict():
    finding = ReviewFinding(
        finding_id="f1",
        severity="high",
        title="missing test",
        evidence="no test found",
        file="src/x.py",
        line=10,
        requested_change="add test",
    )
    data = finding.to_dict()
    assert data["severity"] == "high"
    assert data["file"] == "src/x.py"


def test_enum_str_subclass():
    # Enums are str subclasses so they serialize cleanly and compare to strings.
    assert AgentRole.COORDINATOR == "coordinator"
    assert ReviewVerdict.APPROVE == "approve"
    assert TeamStopReason.BLOCKED == "blocked"
