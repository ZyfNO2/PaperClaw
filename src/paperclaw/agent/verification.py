from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal


ClaimSource = Literal["user", "inferred", "project_rule"]
CheckType = Literal["file_exists", "file_contains", "file_hash", "command", "tests", "history"]
EvidenceStatus = Literal["passed", "failed", "error", "skipped"]
VerificationStatus = Literal["passed", "failed", "incomplete", "error"]
ReflectionDecisionType = Literal["accept", "continue", "repair", "reverify", "blocked"]
VerificationStopReason = Literal[
    "completed_verified",
    "verification_failed",
    "verification_incomplete",
    "reflection_limit",
    "repeated_failure",
    "max_steps",
    "timeout",
    "blocked_environment",
    "cancelled",
    "internal_error",
]


@dataclass
class TaskClaim:
    """One concrete acceptance claim that Verify must either cover with evidence or leave explicitly uncovered."""

    claim_id: str
    description: str
    checkable: bool
    required: bool
    source: ClaimSource

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationCheck:
    """A deterministic check definition.

    v0.02 keeps checks structured so Reflection can consume evidence without inventing new tests or commands ad hoc.
    """

    check_id: str
    claim_ids: list[str]
    check_type: CheckType
    arguments: dict
    required: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationPlan:
    """Structured verification worklist built after a completion proposal."""

    task_claims: list[TaskClaim]
    checks: list[VerificationCheck]
    generated_from: str
    created_after_step: int

    def to_dict(self) -> dict:
        return {
            "task_claims": [claim.to_dict() for claim in self.task_claims],
            "checks": [check.to_dict() for check in self.checks],
            "generated_from": self.generated_from,
            "created_after_step": self.created_after_step,
        }


@dataclass
class VerificationEvidence:
    """Observed result for one verification check.

    Evidence is immutable runtime fact. Reflection may interpret it, but must never rewrite or upgrade it in place.
    """

    evidence_id: str
    check_id: str
    status: EvidenceStatus
    observed: str
    source_tool: str | None
    source_step: int | None
    exit_code: int | None
    timestamp: datetime

    def to_dict(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class VerificationResult:
    """Merged verification outcome for the current completion proposal."""

    status: VerificationStatus
    checks: list[VerificationEvidence]
    passed_claim_ids: list[str]
    failed_claim_ids: list[str]
    uncovered_claim_ids: list[str]
    verified_after_last_write: bool
    summary: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
            "passed_claim_ids": self.passed_claim_ids,
            "failed_claim_ids": self.failed_claim_ids,
            "uncovered_claim_ids": self.uncovered_claim_ids,
            "verified_after_last_write": self.verified_after_last_write,
            "summary": self.summary,
        }


@dataclass
class DoneProposal:
    """A model claim that the run is ready to finish.

    v0.01 accepts it directly; v0.02 keeps the proposal structured now so Verify/Reflection can gate it next.
    """

    result: str
    claimed_verification: str = ""
    remaining_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReflectionDecision:
    """Bounded reflection output describing whether evidence is enough to accept or what the next move should be."""

    decision: ReflectionDecisionType
    evidence_ids: list[str]
    failed_claim_ids: list[str]
    next_action: str | None
    reason_code: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)
