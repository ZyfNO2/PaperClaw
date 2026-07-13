"""Independent Reviewer for the MultiAgent team.

The Reviewer does not modify implementation. It receives read-only context
(user goal, DAG, diff, evidence, trace) and produces structured findings with
a verdict. Blocker/high findings must become Fix Tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from paperclaw.multiagent.contracts import (
    AgentTask,
    ReviewFinding,
    ReviewVerdict,
    WorkerResult,
)
from paperclaw.multiagent.events import emit_team_event


@dataclass
class ReviewReport:
    """Structured output of a Reviewer pass."""

    verdict: ReviewVerdict
    findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict),
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
        }


class Reviewer:
    """Read-only reviewer that inspects task results and evidence.

    v0.03 provides a deterministic rule-based reviewer suitable for tests and
    small tasks. Future versions can plug in an LLM-based reviewer behind the
    same interface.
    """

    def __init__(self, agent_id: str, team_state: dict) -> None:
        self.agent_id = agent_id
        self._team_state = team_state

    def review(
        self,
        user_goal: str,
        dag: list[AgentTask],
        results: dict[str, WorkerResult],
        workspace: Path,
    ) -> ReviewReport:
        """Inspect completed work and return findings.

        The Reviewer only reads. It never writes files, acquires leases, or calls
        mutating tools.
        """

        emit_team_event(
            self._team_state,
            "review.started",
            self.agent_id,
            "review",
            user_goal=user_goal,
            task_count=len(dag),
        )

        findings: list[ReviewFinding] = []
        changed_files: set[str] = set()
        for result in results.values():
            changed_files.update(result.changed_files)
            if result.status != "completed":
                findings.append(
                    ReviewFinding(
                        finding_id=f"find-{uuid4().hex[:8]}",
                        severity="high",
                        title=f"Task {result.task_id} did not complete",
                        evidence=f"status={result.status}, summary={result.summary}",
                        requested_change="Investigate failure or create Fix Task",
                    )
                )
            if result.verification_result is not None and result.verification_result.status != "passed":
                findings.append(
                    ReviewFinding(
                        finding_id=f"find-{uuid4().hex[:8]}",
                        severity="blocker",
                        title=f"Task {result.task_id} verification not passed",
                        evidence=result.verification_result.summary,
                        requested_change="Add or fix verification evidence before completing",
                    )
                )

        # Check that expected artifacts (files) exist.
        for task in dag:
            for expected in task.expected_artifacts:
                resolved = (workspace / expected).resolve()
                if not resolved.is_file():
                    findings.append(
                        ReviewFinding(
                            finding_id=f"find-{uuid4().hex[:8]}",
                            severity="high",
                            title=f"Expected artifact missing: {expected}",
                            evidence=f"{expected} not found in workspace",
                            file=expected,
                            requested_change=f"Produce {expected} or update expected_artifacts",
                        )
                    )

        verdict = self._derive_verdict(findings)
        report = ReviewReport(
            verdict=verdict,
            findings=findings,
            summary=f"Reviewed {len(dag)} tasks, {len(findings)} findings, verdict={verdict.value}",
        )

        emit_team_event(
            self._team_state,
            "review.completed",
            self.agent_id,
            "review",
            verdict=verdict.value,
            finding_count=len(findings),
        )
        return report

    def _derive_verdict(self, findings: list[ReviewFinding]) -> ReviewVerdict:
        """Map finding severities to a verdict."""

        severities = {f.severity for f in findings}
        if "blocker" in severities:
            return ReviewVerdict.BLOCKED
        if "high" in severities:
            return ReviewVerdict.REQUEST_CHANGES
        return ReviewVerdict.APPROVE
