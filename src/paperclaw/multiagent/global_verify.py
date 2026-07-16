"""Deterministic cross-task verification for MultiAgent runs.

The v0.03 Worker owns only local completion. This module adds an opt-in project
level gate that runs after the existing Coordinator and verifies explicit claims
spanning multiple tasks. It is deliberately composition-based so the established
Coordinator path and the v0.07.x stack do not need to be modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4

from paperclaw.multiagent.contracts import (
    AgentTask,
    ReviewFinding,
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.coordinator import CoordinatorResult


class GlobalClaimRule(str, Enum):
    """Deterministic aggregation rule for one project-level claim."""

    ALL_PRESENT = "all_present"
    ALL_EQUAL = "all_equal"


class GlobalVerificationStatus(str, Enum):
    """Outcome of the project-level verification gate."""

    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    SKIPPED = "skipped"


class GlobalVerifyContractError(ValueError):
    """Raised when project claims reference an invalid task contract."""


@dataclass(frozen=True)
class ProjectClaim:
    """One explicit invariant spanning one or more Worker tasks.

    ``evidence_key`` identifies a structured value supplied for each contributor
    task. ``ALL_PRESENT`` requires every contributor to publish that key;
    ``ALL_EQUAL`` additionally requires all canonical values to match.
    """

    claim_id: str
    description: str
    contributor_task_ids: tuple[str, ...]
    evidence_key: str
    rule: GlobalClaimRule = GlobalClaimRule.ALL_PRESENT
    required: bool = True

    def __post_init__(self) -> None:
        if not self.claim_id.strip():
            raise GlobalVerifyContractError("claim_id must not be empty")
        if not self.description.strip():
            raise GlobalVerifyContractError(
                f"claim {self.claim_id!r} must have a description"
            )
        if not self.contributor_task_ids:
            raise GlobalVerifyContractError(
                f"claim {self.claim_id!r} must name contributor tasks"
            )
        if len(set(self.contributor_task_ids)) != len(self.contributor_task_ids):
            raise GlobalVerifyContractError(
                f"claim {self.claim_id!r} contains duplicate contributor tasks"
            )
        if not self.evidence_key.strip():
            raise GlobalVerifyContractError(
                f"claim {self.claim_id!r} must define an evidence_key"
            )


@dataclass(frozen=True)
class GlobalVerificationReport:
    """Sanitized aggregate facts produced by the global verification gate."""

    status: GlobalVerificationStatus
    passed_claim_ids: tuple[str, ...] = ()
    failed_claim_ids: tuple[str, ...] = ()
    uncovered_claim_ids: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    summary: str = ""

    @property
    def accepted(self) -> bool:
        return self.status == GlobalVerificationStatus.PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "passed_claim_ids": list(self.passed_claim_ids),
            "failed_claim_ids": list(self.failed_claim_ids),
            "uncovered_claim_ids": list(self.uncovered_claim_ids),
            "issues": list(self.issues),
            "summary": self.summary,
        }


@dataclass
class GlobalVerifiedCoordinatorResult:
    """Coordinator-compatible result with an enforced global verification gate."""

    stop_reason: TeamStopReason
    task_results: dict[str, WorkerResult] = field(default_factory=dict)
    review_findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    global_verification: GlobalVerificationReport = field(
        default_factory=lambda: GlobalVerificationReport(
            status=GlobalVerificationStatus.SKIPPED,
            summary="global verification was not executed",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stop_reason": self.stop_reason.value,
            "task_results": {
                task_id: result.to_dict()
                for task_id, result in self.task_results.items()
            },
            "review_findings": [finding.to_dict() for finding in self.review_findings],
            "summary": self.summary,
            "trace_events": list(self.trace_events),
            "global_verification": self.global_verification.to_dict(),
        }


class CoordinatorLike(Protocol):
    """The existing Coordinator surface consumed by the composition wrapper."""

    def run(self, user_goal: str, tasks: list[AgentTask]) -> CoordinatorResult: ...


class GlobalVerifier:
    """Evaluate explicit cross-task claims without invoking a model or tools."""

    def verify(
        self,
        *,
        tasks: Sequence[AgentTask],
        results: Mapping[str, WorkerResult],
        claims: Sequence[ProjectClaim],
        evidence_by_task: Mapping[str, Mapping[str, Any]],
    ) -> GlobalVerificationReport:
        task_ids = [task.task_id for task in tasks]
        if len(set(task_ids)) != len(task_ids):
            raise GlobalVerifyContractError("task ids must be unique")
        task_id_set = set(task_ids)

        claim_ids = [claim.claim_id for claim in claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise GlobalVerifyContractError("project claim ids must be unique")
        if not claims:
            return GlobalVerificationReport(
                status=GlobalVerificationStatus.INCOMPLETE,
                issues=("no project-level claims were supplied",),
                summary="global verification incomplete: no project claims",
            )

        passed: list[str] = []
        failed: list[str] = []
        uncovered: list[str] = []
        issues: list[str] = []

        for claim in claims:
            unknown_tasks = sorted(set(claim.contributor_task_ids) - task_id_set)
            if unknown_tasks:
                raise GlobalVerifyContractError(
                    f"claim {claim.claim_id!r} references unknown tasks: "
                    + ", ".join(unknown_tasks)
                )

            non_completed = [
                task_id
                for task_id in claim.contributor_task_ids
                if not _worker_completed(results.get(task_id))
            ]
            if non_completed:
                failed.append(claim.claim_id)
                issues.append(
                    f"claim {claim.claim_id}: contributor tasks not completed: "
                    + ", ".join(non_completed)
                )
                continue

            values: list[str] = []
            missing: list[str] = []
            for task_id in claim.contributor_task_ids:
                task_evidence = evidence_by_task.get(task_id, {})
                if claim.evidence_key not in task_evidence:
                    missing.append(task_id)
                    continue
                values.append(_canonical_value(task_evidence[claim.evidence_key]))

            if missing:
                if claim.required:
                    uncovered.append(claim.claim_id)
                else:
                    passed.append(claim.claim_id)
                issues.append(
                    f"claim {claim.claim_id}: evidence {claim.evidence_key!r} "
                    f"missing for {', '.join(missing)}"
                )
                continue

            if claim.rule == GlobalClaimRule.ALL_EQUAL and len(set(values)) != 1:
                failed.append(claim.claim_id)
                issues.append(
                    f"claim {claim.claim_id}: contributor evidence disagrees "
                    f"({len(set(values))} distinct canonical values)"
                )
                continue

            passed.append(claim.claim_id)

        if failed:
            status = GlobalVerificationStatus.FAILED
        elif uncovered:
            status = GlobalVerificationStatus.INCOMPLETE
        else:
            status = GlobalVerificationStatus.PASSED

        return GlobalVerificationReport(
            status=status,
            passed_claim_ids=tuple(passed),
            failed_claim_ids=tuple(failed),
            uncovered_claim_ids=tuple(uncovered),
            issues=tuple(issues),
            summary=(
                "global verification "
                f"{status.value}: passed={len(passed)} failed={len(failed)} "
                f"uncovered={len(uncovered)}"
            ),
        )


class GlobalVerifyCoordinator:
    """Run the existing Coordinator and enforce a project-level claim gate.

    The wrapper does not mutate the wrapped Coordinator. When the existing team
    does not reach a successful terminal state, global verification is skipped and
    the original stop reason is preserved. When the team succeeds locally but the
    project claims fail or remain uncovered, the effective result is BLOCKED.
    """

    def __init__(
        self,
        coordinator: CoordinatorLike,
        verifier: GlobalVerifier | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._verifier = verifier or GlobalVerifier()

    def run(
        self,
        user_goal: str,
        tasks: list[AgentTask],
        *,
        claims: Sequence[ProjectClaim],
        evidence_by_task: Mapping[str, Mapping[str, Any]],
    ) -> GlobalVerifiedCoordinatorResult:
        base = self._coordinator.run(user_goal, tasks)
        base_stop = _team_stop_reason(base.stop_reason)

        if base_stop not in {
            TeamStopReason.COMPLETED,
            TeamStopReason.ALL_TASKS_COMPLETED,
        }:
            report = GlobalVerificationReport(
                status=GlobalVerificationStatus.SKIPPED,
                issues=(
                    f"team stopped before global verification: {base_stop.value}",
                ),
                summary="global verification skipped because the team did not complete",
            )
            effective_stop = base_stop
        else:
            report = self._verifier.verify(
                tasks=tasks,
                results=base.task_results,
                claims=claims,
                evidence_by_task=evidence_by_task,
            )
            effective_stop = (
                base_stop if report.accepted else TeamStopReason.BLOCKED
            )

        trace_events = [dict(event) for event in base.trace_events]
        trace_events.append(
            _global_verify_event(trace_events, report, effective_stop)
        )
        summary = (
            f"{base.summary}; {report.summary}"
            if base.summary
            else report.summary
        )
        return GlobalVerifiedCoordinatorResult(
            stop_reason=effective_stop,
            task_results=dict(base.task_results),
            review_findings=list(base.review_findings),
            summary=summary,
            trace_events=trace_events,
            global_verification=report,
        )


def _worker_completed(result: WorkerResult | None) -> bool:
    if result is None:
        return False
    status = result.status.value if isinstance(result.status, WorkerStatus) else str(result.status)
    return status == WorkerStatus.COMPLETED.value


def _team_stop_reason(value: TeamStopReason | str) -> TeamStopReason:
    if isinstance(value, TeamStopReason):
        return value
    text = str(value)
    try:
        return TeamStopReason(text)
    except ValueError:
        prefix = "TeamStopReason."
        if text.startswith(prefix):
            return TeamStopReason[text.removeprefix(prefix)]
        return TeamStopReason.INTERNAL_ERROR


def _canonical_value(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


def _global_verify_event(
    existing: Sequence[Mapping[str, Any]],
    report: GlobalVerificationReport,
    stop_reason: TeamStopReason,
) -> dict[str, Any]:
    sequence = max(
        (
            int(event.get("sequence", 0))
            for event in existing
            if isinstance(event.get("sequence"), int)
        ),
        default=0,
    ) + 1
    run_id = next(
        (
            str(event["run_id"])
            for event in reversed(existing)
            if event.get("run_id")
        ),
        "unknown-global-verify-run",
    )
    return {
        "event_id": f"evt-{uuid4().hex[:12]}",
        "event_type": "global_verification.completed",
        "schema_version": "v1",
        "run_id": run_id,
        "agent_id": "global-verifier",
        "task_id": "global-verify",
        "sequence": sequence,
        "payload": {
            "status": report.status.value,
            "passed_count": len(report.passed_claim_ids),
            "failed_count": len(report.failed_claim_ids),
            "uncovered_count": len(report.uncovered_claim_ids),
            "effective_stop_reason": stop_reason.value,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "GlobalClaimRule",
    "GlobalVerificationReport",
    "GlobalVerificationStatus",
    "GlobalVerifiedCoordinatorResult",
    "GlobalVerifier",
    "GlobalVerifyContractError",
    "GlobalVerifyCoordinator",
    "ProjectClaim",
]
