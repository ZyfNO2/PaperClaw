from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from paperclaw.multiagent.contracts import (
    AgentTask,
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.coordinator import CoordinatorResult
from paperclaw.multiagent.global_verify import (
    GlobalClaimRule,
    GlobalVerificationStatus,
    GlobalVerifier,
    GlobalVerifyContractError,
    GlobalVerifyCoordinator,
    ProjectClaim,
)


@dataclass
class StubCoordinator:
    result: CoordinatorResult
    calls: int = 0

    def run(self, user_goal: str, tasks: list[AgentTask]) -> CoordinatorResult:
        assert user_goal
        assert tasks
        self.calls += 1
        return self.result


def test_global_verify_blocks_local_success_when_shared_contract_disagrees() -> None:
    tasks = [_task("api"), _task("client")]
    base = _completed_team_result(tasks)
    coordinator = StubCoordinator(base)
    gate = GlobalVerifyCoordinator(coordinator)

    result = gate.run(
        "ship compatible API and client",
        tasks,
        claims=[
            ProjectClaim(
                claim_id="shared-schema",
                description="API and client use the same schema",
                contributor_task_ids=("api", "client"),
                evidence_key="schema_digest",
                rule=GlobalClaimRule.ALL_EQUAL,
            )
        ],
        evidence_by_task={
            "api": {"schema_digest": "sha256:aaa"},
            "client": {"schema_digest": "sha256:bbb"},
        },
    )

    assert coordinator.calls == 1
    assert result.stop_reason == TeamStopReason.BLOCKED
    assert result.global_verification.status == GlobalVerificationStatus.FAILED
    assert result.global_verification.failed_claim_ids == ("shared-schema",)
    assert result.trace_events[-1]["event_type"] == "global_verification.completed"
    assert result.trace_events[-1]["payload"] == {
        "status": "failed",
        "passed_count": 0,
        "failed_count": 1,
        "uncovered_count": 0,
        "effective_stop_reason": "blocked",
    }


def test_global_verify_accepts_matching_cross_task_evidence() -> None:
    tasks = [_task("api"), _task("client")]
    gate = GlobalVerifyCoordinator(StubCoordinator(_completed_team_result(tasks)))

    result = gate.run(
        "ship compatible API and client",
        tasks,
        claims=[
            ProjectClaim(
                claim_id="shared-schema",
                description="API and client use the same schema",
                contributor_task_ids=("api", "client"),
                evidence_key="schema",
                rule=GlobalClaimRule.ALL_EQUAL,
            ),
            ProjectClaim(
                claim_id="release-notes",
                description="Every contributor published release evidence",
                contributor_task_ids=("api", "client"),
                evidence_key="release_note",
            ),
        ],
        evidence_by_task={
            "api": {"schema": {"version": 1}, "release_note": "api-ready"},
            "client": {"schema": {"version": 1}, "release_note": "client-ready"},
        },
    )

    assert result.stop_reason == TeamStopReason.ALL_TASKS_COMPLETED
    assert result.global_verification.accepted is True
    assert result.global_verification.passed_claim_ids == (
        "shared-schema",
        "release-notes",
    )
    assert result.to_dict()["global_verification"]["status"] == "passed"


def test_missing_required_global_evidence_is_incomplete_and_blocks() -> None:
    tasks = [_task("api"), _task("client")]
    gate = GlobalVerifyCoordinator(StubCoordinator(_completed_team_result(tasks)))

    result = gate.run(
        "ship compatible API and client",
        tasks,
        claims=[
            ProjectClaim(
                claim_id="shared-schema",
                description="API and client publish schema evidence",
                contributor_task_ids=("api", "client"),
                evidence_key="schema",
            )
        ],
        evidence_by_task={"api": {"schema": "v1"}, "client": {}},
    )

    assert result.stop_reason == TeamStopReason.BLOCKED
    assert result.global_verification.status == GlobalVerificationStatus.INCOMPLETE
    assert result.global_verification.uncovered_claim_ids == ("shared-schema",)
    assert "client" in result.global_verification.issues[0]


def test_non_completed_contributor_fails_claim_without_inspecting_evidence() -> None:
    tasks = [_task("api"), _task("client")]
    results = {
        "api": _worker_result("api"),
        "client": _worker_result("client", status=WorkerStatus.FAILED),
    }

    report = GlobalVerifier().verify(
        tasks=tasks,
        results=results,
        claims=[
            ProjectClaim(
                claim_id="integration",
                description="Both contributors completed",
                contributor_task_ids=("api", "client"),
                evidence_key="digest",
                rule=GlobalClaimRule.ALL_EQUAL,
            )
        ],
        evidence_by_task={
            "api": {"digest": "same"},
            "client": {"digest": "same"},
        },
    )

    assert report.status == GlobalVerificationStatus.FAILED
    assert report.failed_claim_ids == ("integration",)
    assert "not completed" in report.issues[0]


def test_project_claim_contract_rejects_unknown_task_reference() -> None:
    with pytest.raises(GlobalVerifyContractError, match="unknown tasks"):
        GlobalVerifier().verify(
            tasks=[_task("api")],
            results={"api": _worker_result("api")},
            claims=[
                ProjectClaim(
                    claim_id="integration",
                    description="Cross-task contract",
                    contributor_task_ids=("api", "missing"),
                    evidence_key="digest",
                )
            ],
            evidence_by_task={"api": {"digest": "x"}},
        )


def test_global_verify_is_skipped_when_team_did_not_complete() -> None:
    tasks = [_task("api")]
    base = CoordinatorResult(
        stop_reason=TeamStopReason.BUDGET_EXHAUSTED,
        task_results={"api": _worker_result("api", status=WorkerStatus.CANCELLED)},
        summary="budget exhausted",
        trace_events=[_event(sequence=1)],
    )
    result = GlobalVerifyCoordinator(StubCoordinator(base)).run(
        "bounded task",
        tasks,
        claims=[
            ProjectClaim(
                claim_id="artifact",
                description="Artifact exists",
                contributor_task_ids=("api",),
                evidence_key="digest",
            )
        ],
        evidence_by_task={"api": {"digest": "x"}},
    )

    assert result.stop_reason == TeamStopReason.BUDGET_EXHAUSTED
    assert result.global_verification.status == GlobalVerificationStatus.SKIPPED


def _task(task_id: str) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        title=task_id,
        objective=f"implement {task_id}",
        acceptance_criteria=[f"{task_id} complete"],
    )


def _worker_result(
    task_id: str,
    *,
    status: WorkerStatus = WorkerStatus.COMPLETED,
) -> WorkerResult:
    return WorkerResult(task_id=task_id, status=status, summary=f"{task_id} done")


def _completed_team_result(tasks: list[AgentTask]) -> CoordinatorResult:
    return CoordinatorResult(
        stop_reason=TeamStopReason.ALL_TASKS_COMPLETED,
        task_results={task.task_id: _worker_result(task.task_id) for task in tasks},
        summary="all local tasks completed",
        trace_events=[_event(sequence=1)],
    )


def _event(*, sequence: int) -> dict[str, Any]:
    return {
        "event_id": f"evt-{sequence}",
        "event_type": "team.stopped",
        "schema_version": "v1",
        "run_id": "team-run",
        "agent_id": "coordinator",
        "task_id": "root",
        "sequence": sequence,
        "payload": {"stop_reason": "all_tasks_completed"},
        "timestamp": "2026-07-16T00:00:00+00:00",
    }
