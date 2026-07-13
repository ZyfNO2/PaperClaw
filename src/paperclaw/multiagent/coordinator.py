"""Coordinator for the v0.03 MultiAgent team.

The Coordinator owns the team state, validates the Task DAG, schedules ready
Workers, handles failures, and requests independent Review. It does not do the
implementation work itself.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable
from uuid import uuid4

from paperclaw.models.base import ChatModel
from paperclaw.multiagent.contracts import (
    AgentRole,
    AgentTask,
    ReviewFinding,
    ReviewVerdict,
    TaskStatus,
    TeamBudget,
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.dag import compute_task_status, validate_task_dag
from paperclaw.multiagent.events import emit_team_event
from paperclaw.multiagent.lease import LeaseManager
from paperclaw.multiagent.permissions import PermissionGuardLite
from paperclaw.multiagent.reviewer import Reviewer
from paperclaw.multiagent.worker import Worker


@dataclass
class CoordinatorResult:
    """Final result of a Coordinator run."""

    stop_reason: TeamStopReason
    task_results: dict[str, WorkerResult] = field(default_factory=dict)
    review_findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""
    trace_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stop_reason": str(self.stop_reason),
            "task_results": {tid: r.to_dict() for tid, r in self.task_results.items()},
            "review_findings": [f.to_dict() for f in self.review_findings],
            "summary": self.summary,
            "trace_events": self.trace_events,
        }


class Coordinator:
    """Orchestrate a team of Workers and an independent Reviewer.

    The Coordinator is single-instance per run. It keeps the authoritative team
    state and makes scheduling decisions. Workers run in background threads but
    share no mutable state except the event trace (which is lock-protected).
    """

    def __init__(
        self,
        model_factory: Callable[[str], ChatModel],
        workspace: Path | str,
        budget: TeamBudget | None = None,
        enable_verification_gate: bool = True,
        event_handler: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._model_factory = model_factory
        self.workspace = Path(workspace).resolve(strict=True)
        self.budget = budget or TeamBudget()
        self.enable_verification_gate = enable_verification_gate
        self._event_handler = event_handler

        self._guard = PermissionGuardLite(self.workspace)
        self._lease_manager = LeaseManager(self.workspace)
        self._team_state = self._initial_team_state()

    def _initial_team_state(self) -> dict:
        return {
            "run_id": f"team-{uuid4().hex[:12]}",
            "event_sequence": 0,
            "trace_events": [],
            "event_handler": self._event_handler,
            "total_steps": 0,
            "total_model_calls": 0,
            "total_tool_calls": 0,
            "fix_round_count": 0,
        }

    def run(self, user_goal: str, tasks: list[AgentTask]) -> CoordinatorResult:
        """Run the team on a goal and task DAG.

        If the DAG is invalid or the split decision rejects parallelism, the
        Coordinator falls back to sequential single-agent execution.
        """

        emit_team_event(
            self._team_state,
            "team.started",
            AgentRole.COORDINATOR.value,
            "root",
            user_goal=user_goal,
            task_count=len(tasks),
        )

        if not tasks:
            return CoordinatorResult(
                stop_reason=TeamStopReason.COMPLETED,
                summary="no tasks provided",
                trace_events=list(self._team_state["trace_events"]),
            )

        dag_check = validate_task_dag(tasks)
        if not dag_check.valid:
            emit_team_event(
                self._team_state,
                "team.dag_invalid",
                AgentRole.COORDINATOR.value,
                "root",
                errors=dag_check.errors,
            )
            return CoordinatorResult(
                stop_reason=TeamStopReason.BLOCKED,
                summary=f"DAG invalid: {'; '.join(dag_check.errors)}",
                trace_events=list(self._team_state["trace_events"]),
            )

        if not self._worth_parallelizing(tasks):
            return self._run_single_agent(user_goal, tasks[0])

        return self._run_parallel(user_goal, tasks)

    def _worth_parallelizing(self, tasks: list[AgentTask]) -> bool:
        """Heuristic gate: should we run tasks in parallel?

        Parallelism pays off when there are at least two independent subtasks
        with meaningful independent value. Write-scope isolation is checked by
        validate_task_dag; shared directories (e.g. "src") do not prevent
        parallel execution because LeaseManager enforces file-level exclusivity.
        """

        if len(tasks) < 2:
            return False
        # Count tasks with no mutual dependencies.
        independent_pairs = 0
        for i, a in enumerate(tasks):
            for b in tasks[i + 1 :]:
                if b.task_id not in a.dependencies and a.task_id not in b.dependencies:
                    independent_pairs += 1
        return independent_pairs > 0

    def _run_single_agent(self, user_goal: str, task: AgentTask) -> CoordinatorResult:
        """Fallback path for tasks that do not benefit from parallelization."""

        emit_team_event(
            self._team_state,
            "team.single_agent_path",
            AgentRole.COORDINATOR.value,
            task.task_id,
            reason="not worth parallelizing",
        )
        worker = self._make_worker("worker-0")
        result = worker.run(task, self.workspace)
        return CoordinatorResult(
            stop_reason=TeamStopReason.COMPLETED if result.status == WorkerStatus.COMPLETED else TeamStopReason.BLOCKED,
            task_results={task.task_id: result},
            summary=f"Single-agent path: {result.summary}",
            trace_events=list(self._team_state["trace_events"]),
        )

    def _run_parallel(self, user_goal: str, tasks: list[AgentTask]) -> CoordinatorResult:
        """Parallel execution with bounded Workers and independent Review."""

        results: dict[str, WorkerResult] = {}
        statuses: dict[str, TaskStatus] = {t.task_id: TaskStatus.PENDING for t in tasks}
        failed: set[str] = set()
        cancelled: set[str] = set()
        active_workers: dict[str, WorkerThread] = {}
        result_queue: Queue[tuple[str, WorkerResult]] = Queue()
        lock = threading.Lock()

        start_time = time.monotonic()
        stop_reason: TeamStopReason | None = None

        while True:
            # Budget checks
            if self._budget_exhausted(start_time):
                stop_reason = TeamStopReason.BUDGET_EXHAUSTED
                break

            # Schedule ready tasks
            with lock:
                for task in tasks:
                    if statuses[task.task_id] != TaskStatus.PENDING:
                        continue
                    if all(
                        statuses.get(dep) == TaskStatus.COMPLETED for dep in task.dependencies
                    ) and len(active_workers) < self.budget.max_agents:
                        statuses[task.task_id] = TaskStatus.RUNNING
                        worker = self._make_worker(f"worker-{len(active_workers)}")
                        thread = WorkerThread(worker, task, self.workspace, result_queue)
                        active_workers[task.task_id] = thread
                        thread.start()

            # Collect finished Workers
            try:
                while True:
                    task_id, result = result_queue.get_nowait()
                    with lock:
                        active_workers.pop(task_id, None)
                        results[task_id] = result
                        if result.status == WorkerStatus.COMPLETED:
                            statuses[task_id] = TaskStatus.COMPLETED
                        elif result.status == WorkerStatus.CANCELLED:
                            cancelled.add(task_id)
                            statuses[task_id] = TaskStatus.CANCELLED
                        else:
                            failed.add(task_id)
                            statuses[task_id] = TaskStatus.FAILED
                            # Block downstream tasks
                            for t in tasks:
                                if task_id in t.dependencies and statuses[t.task_id] == TaskStatus.PENDING:
                                    statuses[t.task_id] = TaskStatus.BLOCKED
            except Empty:
                pass

            # Termination conditions
            with lock:
                if all(s in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED} for s in statuses.values()):
                    if failed or cancelled:
                        stop_reason = TeamStopReason.BLOCKED
                    else:
                        stop_reason = TeamStopReason.ALL_TASKS_COMPLETED
                    break
                if not active_workers and any(s == TaskStatus.PENDING for s in statuses.values()):
                    # Deadlock: pending but nothing active and nothing can start
                    stop_reason = TeamStopReason.BLOCKED
                    break

            # Throttle polling
            if active_workers:
                time.sleep(0.05)

        # Wait for any stragglers and cancel if needed
        for task_id, thread in list(active_workers.items()):
            thread.join(timeout=5)
            if thread.is_alive():
                # Cooperative cancellation: signal the Worker, then give it a
                # short grace period to finish the current step.
                thread.worker.cancel(thread.task)
                thread.join(timeout=3)
                if thread.is_alive():
                    emit_team_event(
                        self._team_state,
                        "worker.cancel_failed",
                        thread.worker.agent_id,
                        task_id,
                        reason="thread did not terminate after cooperative cancel",
                    )
                thread.result = WorkerResult(
                    task_id=task_id,
                    status=WorkerStatus.CANCELLED,
                    summary="cancelled during shutdown",
                )
            results[task_id] = thread.result

        # Review if all tasks completed
        review_findings: list[ReviewFinding] = []
        if stop_reason == TeamStopReason.ALL_TASKS_COMPLETED:
            reviewer = Reviewer("reviewer-0", self._team_state)
            report = reviewer.review(user_goal, tasks, results, self.workspace)
            review_findings = report.findings
            if report.verdict == ReviewVerdict.BLOCKED:
                stop_reason = TeamStopReason.BLOCKED
            elif report.verdict == ReviewVerdict.REQUEST_CHANGES:
                if self._team_state["fix_round_count"] < self.budget.max_fix_rounds:
                    self._team_state["fix_round_count"] += 1
                    # TODO: create Fix Tasks and re-run; for v0.03 report blocked.
                    stop_reason = TeamStopReason.BLOCKED
                else:
                    stop_reason = TeamStopReason.REFLECTION_LIMIT

        summary = self._build_summary(stop_reason, results, review_findings)
        emit_team_event(
            self._team_state,
            "team.stopped",
            AgentRole.COORDINATOR.value,
            "root",
            stop_reason=str(stop_reason),
            summary=summary,
        )
        return CoordinatorResult(
            stop_reason=stop_reason,
            task_results=results,
            review_findings=review_findings,
            summary=summary,
            trace_events=list(self._team_state["trace_events"]),
        )

    def _make_worker(self, agent_id: str) -> Worker:
        return Worker(
            agent_id=agent_id,
            model=self._model_factory(agent_id),
            guard=self._guard,
            lease_manager=self._lease_manager,
            team_state=self._team_state,
            enable_verification_gate=self.enable_verification_gate,
        )

    def _budget_exhausted(self, start_time: float) -> bool:
        """Check wall time budget. Step/model budgets are enforced per Worker."""

        elapsed = time.monotonic() - start_time
        return elapsed > self.budget.max_wall_time_seconds

    def _build_summary(
        self,
        stop_reason: TeamStopReason,
        results: dict[str, WorkerResult],
        findings: list[ReviewFinding],
    ) -> str:
        completed = sum(1 for r in results.values() if r.status == WorkerStatus.COMPLETED)
        total = len(results)
        return (
            f"stop={stop_reason.value}, completed={completed}/{total}, "
            f"findings={len(findings)}, fix_rounds={self._team_state['fix_round_count']}"
        )


class WorkerThread(threading.Thread):
    """Thin thread wrapper that runs one Worker and puts the result on a queue."""

    def __init__(
        self,
        worker: Worker,
        task: AgentTask,
        workspace: Path,
        result_queue: Queue[tuple[str, WorkerResult]],
    ) -> None:
        super().__init__(daemon=True)
        self.worker = worker
        self.task = task
        self.workspace = workspace
        self.result_queue = result_queue
        self.result = WorkerResult(
            task_id=task.task_id,
            status=WorkerStatus.CANCELLED,
            summary="thread did not produce result",
        )

    def run(self) -> None:
        self.result = self.worker.run(self.task, self.workspace)
        self.result_queue.put((self.task.task_id, self.result))
