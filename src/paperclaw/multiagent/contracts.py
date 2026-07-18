"""Structured contracts for the v0.03 MultiAgent team.

All inter-agent communication is explicit: tasks, results, messages, findings,
and workspace leases are dataclasses that can be serialized and audited. Free-form
model text is never treated as a team message.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from paperclaw.agent.verification import VerificationResult


class TaskStatus(str, Enum):
    """Lifecycle of a task inside the Coordinator queue."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class WorkerStatus(str, Enum):
    """Terminal or transient status returned by a Worker."""

    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class AgentRole(str, Enum):
    """Roles supported by the v0.03 team model."""

    COORDINATOR = "coordinator"
    WORKER = "worker"
    REVIEWER = "reviewer"


class MessageType(str, Enum):
    """Event vocabulary for the team message bus."""

    TASK_ASSIGNED = "task.assigned"
    TASK_ACCEPTED = "task.accepted"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_BLOCKED = "task.blocked"
    ARTIFACT_PUBLISHED = "artifact.published"
    CLARIFICATION_REQUESTED = "clarification.requested"
    CLARIFICATION_ANSWERED = "clarification.answered"
    CANCEL_REQUESTED = "cancel.requested"
    REVIEW_REQUESTED = "review.requested"
    REVIEW_COMPLETED = "review.completed"


class ReviewVerdict(str, Enum):
    """Decision produced by an independent Reviewer."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    BLOCKED = "blocked"


class TeamStopReason(str, Enum):
    """Why the team stopped. Covers success, failure, and bounded termination."""

    COMPLETED = "completed"
    ALL_TASKS_COMPLETED = "all_tasks_completed"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    REFLECTION_LIMIT = "reflection_limit"
    UNKNOWN_OUTCOME = "unknown_outcome"
    INTERNAL_ERROR = "internal_error"


class PermissionDecision(str, Enum):
    """Result of a PermissionGuardLite check."""

    ALLOW = "allow"
    DENY = "deny"


class LeaseDecision(str, Enum):
    """Result of a FileLease acquisition attempt."""

    GRANTED = "granted"
    CONFLICT = "conflict"
    OUTSIDE_WORKSPACE = "outside_workspace"
    ALREADY_OWNS = "already_owns"


@dataclass
class AgentTask:
    """One bounded unit of work assigned to a Worker.

    The Coordinator must define the input, scope, deliverables, and success criteria
    before any Worker starts. A task without acceptance criteria is invalid.
    """

    task_id: str
    title: str
    objective: str
    acceptance_criteria: list[str]
    allowed_paths: list[str] = field(default_factory=list)
    writable_paths: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    parent_task_id: str | None = None
    input_artifact_ids: list[str] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    max_steps: int = 12
    timeout_seconds: int = 120
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SemanticJudgeStatus = Literal[
    "passed",
    "rejected",
    "inconclusive",
    "transient_error",
    "provider_error",
    "protocol_error",
]


@dataclass(frozen=True)
class SemanticJudgeResult:
    """Bounded semantic acceptance result separate from deterministic Verify."""

    status: SemanticJudgeStatus | str
    reason_code: str
    summary: str
    attempt_count: int
    provider: str | None = None
    model: str | None = None
    transient: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerResult:
    """Structured output from a Worker after running one task.

    The Worker does not own global completion. It only reports what it changed,
    what it verified, and what remains unresolved. Counters are reported so the
    Coordinator can enforce the team-wide step and model-call budgets.
    """

    task_id: str
    status: WorkerStatus | str
    summary: str
    changed_files: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    verification_result: VerificationResult | None = None
    semantic_judge_result: SemanticJudgeResult | None = None
    unresolved_items: list[str] = field(default_factory=list)
    handoff_notes: list[str] = field(default_factory=list)
    step_count: int = 0
    model_call_count: int = 0
    tool_call_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.verification_result is not None:
            data["verification_result"] = self.verification_result.to_dict()
        if self.semantic_judge_result is not None:
            data["semantic_judge_result"] = self.semantic_judge_result.to_dict()
        return data


@dataclass
class AgentMessage:
    """One structured message on the team message bus.

    Model-generated prose does not automatically become an AgentMessage. Only the
    Runtime message channel can produce these events.
    """

    message_id: str
    sender_id: str
    recipient_id: str
    message_type: MessageType | str
    task_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Enums inherit from str but asdict preserves the enum instance in some
        # Python versions; force the string value for stable JSON serialization.
        if isinstance(data["message_type"], Enum):
            data["message_type"] = data["message_type"].value
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class FileLease:
    """Exclusive write ownership of a single file for the duration of one task."""

    path: str
    owner_agent_id: str
    task_id: str
    acquired_at: datetime
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["acquired_at"] = self.acquired_at.isoformat()
        data["expires_at"] = self.expires_at.isoformat()
        return data


@dataclass
class ReviewFinding:
    """One issue found by a Reviewer, bound to evidence and location."""

    finding_id: str
    severity: Literal["blocker", "high", "medium", "low"]
    title: str
    evidence: str
    file: str | None = None
    line: int | None = None
    requested_change: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TeamBudget:
    """Shared budget for the whole team run.

    Sub-task budgets must count against the team total. Splitting work across
    Agents must not bypass limits.
    """

    max_agents: int = 3
    max_total_steps: int = 100
    max_total_model_calls: int = 200
    max_wall_time_seconds: int = 600
    max_fix_rounds: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
