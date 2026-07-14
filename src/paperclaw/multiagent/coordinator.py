"""Coordinator for the v0.03 MultiAgent team.

The Coordinator owns the team state, validates the Task DAG, schedules ready
Workers, handles failures, and requests independent Review. It does not do the
implementation work itself.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
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
            "reserved_steps": 0,
            "reserved_model_calls": 0,
            "fix_round_count": 0,
        }

    def _reset_run_state(self) -> None:
        """Initialize per-run mutable state."""

        self._cancelled_task_ids: set[str] = set()
        self._cancel_lock = threading.Lock()

    def run(self, user_goal: str, tasks: list[AgentTask]) -> CoordinatorResult:
        """Run the team on a goal and task DAG.

        If the DAG is invalid or the split decision rejects parallelism, the
        Coordinator falls back to sequential single-agent execution.
        """

        self._reset_run_state()
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

        topo_order = dag_check.topological_order or [t.task_id for t in tasks]
        if not self._worth_parallelizing(tasks):
            return self._run_single_agent(user_goal, tasks, topo_order)

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

    def _run_single_agent(
        self,
        user_goal: str,
        tasks: list[AgentTask],
        topo_order: list[str],
    ) -> CoordinatorResult:
        """Fallback path for tasks that do not benefit from parallelization.

        Even when tasks are not worth running in parallel, the Coordinator must
        still execute every task in topological order and respect dependencies.
        A failure blocks downstream tasks; the final stop reason reflects the
        overall outcome.

        This path enforces the same TeamBudget, deadline, cancel, and Review
        semantics as the parallel path. Previously it bypassed all of them,
        allowing sequential DAGs to exceed max_total_steps / max_total_model_calls
        / max_wall_time_seconds without notice.
        """

        emit_team_event(
            self._team_state,
            "team.single_agent_path",
            AgentRole.COORDINATOR.value,
            "root",
            reason="not worth parallelizing",
            task_count=len(tasks),
        )
        task_by_id = {t.task_id: t for t in tasks}
        results: dict[str, WorkerResult] = {}
        failed_or_blocked = False
        worker = self._make_worker("worker-0")

        # Single absolute wall-clock deadline shared across all tasks and any
        # fix-review rounds that follow. Mirrors _run_parallel semantics.
        run_deadline = time.monotonic() + self.budget.max_wall_time_seconds

        for task_id in topo_order:
            task = task_by_id[task_id]

            # Budget checks — same guards as _execute_task_round.
            if self._deadline_exceeded(run_deadline):
                emit_team_event(
                    self._team_state,
                    "team.budget_exhausted",
                    AgentRole.COORDINATOR.value,
                    "root",
                    reason="wall_time",
                    limit=self.budget.max_wall_time_seconds,
                )
                results[task_id] = WorkerResult(
                    task_id=task_id,
                    status=WorkerStatus.CANCELLED,
                    summary="cancelled: team wall-time budget exhausted",
                )
                failed_or_blocked = True
                continue
            if self._team_steps_exhausted():
                emit_team_event(
                    self._team_state,
                    "team.budget_exhausted",
                    AgentRole.COORDINATOR.value,
                    "root",
                    reason="max_total_steps",
                    limit=self.budget.max_total_steps,
                    consumed=self._team_state["total_steps"],
                )
                results[task_id] = WorkerResult(
                    task_id=task_id,
                    status=WorkerStatus.CANCELLED,
                    summary="cancelled: team step budget exhausted",
                )
                failed_or_blocked = True
                continue
            if self._team_model_calls_exhausted():
                emit_team_event(
                    self._team_state,
                    "team.budget_exhausted",
                    AgentRole.COORDINATOR.value,
                    "root",
                    reason="max_total_model_calls",
                    limit=self.budget.max_total_model_calls,
                    consumed=self._team_state["total_model_calls"],
                )
                results[task_id] = WorkerResult(
                    task_id=task_id,
                    status=WorkerStatus.CANCELLED,
                    summary="cancelled: team model-call budget exhausted",
                )
                failed_or_blocked = True
                continue

            # Cancel check — sequential path must honor external cancel requests.
            if self._is_task_cancelled(task_id):
                results[task_id] = WorkerResult(
                    task_id=task_id,
                    status=WorkerStatus.CANCELLED,
                    summary="cancelled by external request",
                )
                failed_or_blocked = True
                continue

            # If any dependency failed, this task is blocked without running.
            if any(
                results.get(dep).status != WorkerStatus.COMPLETED
                for dep in task.dependencies
                if dep in results
            ):
                results[task_id] = WorkerResult(
                    task_id=task_id,
                    status=WorkerStatus.BLOCKED,
                    summary="blocked because a dependency failed",
                )
                failed_or_blocked = True
                continue

            # Cap task max_steps to remaining team budget so a single Worker
            # cannot consume the entire team step allocation.
            capped_task = self._cap_task_to_remaining_budget(task)

            result = worker.run(capped_task, self.workspace)
            results[task_id] = result
            # Accumulate counters so subsequent tasks see the updated totals.
            self._accumulate_counters(result)
            if result.status != WorkerStatus.COMPLETED:
                failed_or_blocked = True

        # Run Reviewer + Fix-Review loop when all tasks completed, mirroring
        # the parallel path. Previously the sequential path skipped Review
        # entirely, violating SOP §8 (independent review required).
        review_findings: list[ReviewFinding] = []
        stop_reason: TeamStopReason = (
            TeamStopReason.ALL_TASKS_COMPLETED if not failed_or_blocked else TeamStopReason.BLOCKED
        )

        if stop_reason == TeamStopReason.ALL_TASKS_COMPLETED:
            while stop_reason == TeamStopReason.ALL_TASKS_COMPLETED:
                reviewer = Reviewer("reviewer-0", self._team_state)
                report = reviewer.review(user_goal, tasks, results, self.workspace)
                review_findings = report.findings
                emit_team_event(
                    self._team_state,
                    "review.completed",
                    reviewer.agent_id,
                    "review",
                    verdict=report.verdict.value,
                    finding_count=len(report.findings),
                    fix_round=self._team_state["fix_round_count"],
                )

                if report.verdict == ReviewVerdict.APPROVE:
                    break
                if self._team_state["fix_round_count"] >= self.budget.max_fix_rounds:
                    stop_reason = (
                        TeamStopReason.REFLECTION_LIMIT
                        if report.verdict == ReviewVerdict.REQUEST_CHANGES
                        else TeamStopReason.BLOCKED
                    )
                    break

                self._team_state["fix_round_count"] += 1
                fix_tasks = reviewer.create_fix_tasks(report.findings, tasks)
                if not fix_tasks:
                    stop_reason = TeamStopReason.REFLECTION_LIMIT
                    break

                emit_team_event(
                    self._team_state,
                    "team.fix_round_started",
                    AgentRole.COORDINATOR.value,
                    "root",
                    fix_round=self._team_state["fix_round_count"],
                    fix_task_count=len(fix_tasks),
                )
                tasks = tasks + fix_tasks
                for ft in fix_tasks:
                    capped_ft = self._cap_task_to_remaining_budget(ft)
                    fr = worker.run(capped_ft, self.workspace)
                    results[ft.task_id] = fr
                    self._accumulate_counters(fr)
                    if fr.status != WorkerStatus.COMPLETED:
                        stop_reason = TeamStopReason.BLOCKED
                        break

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

    def _run_parallel(self, user_goal: str, tasks: list[AgentTask]) -> CoordinatorResult:
        """Parallel execution with bounded Workers, Review, and fix-review loop."""

        all_results: dict[str, WorkerResult] = {}
        all_tasks: list[AgentTask] = list(tasks)
        review_findings: list[ReviewFinding] = []
        stop_reason: TeamStopReason | None = None

        # Single absolute wall-clock deadline shared across all rounds. This
        # prevents fix-review rounds from resetting the timer and exceeding the
        # team budget.
        run_deadline = time.monotonic() + self.budget.max_wall_time_seconds

        # Initial task execution round.
        round_results, round_statuses, stop_reason = self._execute_task_round(
            user_goal, all_tasks, run_deadline
        )
        all_results.update(round_results)

        # Review/fix loop: keep creating Fix Tasks for blocker/high findings
        # until the Reviewer approves or we hit the round limit.
        while stop_reason == TeamStopReason.ALL_TASKS_COMPLETED:
            reviewer = Reviewer("reviewer-0", self._team_state)
            report = reviewer.review(user_goal, all_tasks, all_results, self.workspace)
            review_findings = report.findings
            emit_team_event(
                self._team_state,
                "review.completed",
                reviewer.agent_id,
                "review",
                verdict=report.verdict.value,
                finding_count=len(report.findings),
                fix_round=self._team_state["fix_round_count"],
            )

            if report.verdict == ReviewVerdict.APPROVE:
                stop_reason = TeamStopReason.ALL_TASKS_COMPLETED
                break

            if report.verdict == ReviewVerdict.REQUEST_CHANGES:
                if self._team_state["fix_round_count"] >= self.budget.max_fix_rounds:
                    stop_reason = TeamStopReason.REFLECTION_LIMIT
                    break
            elif report.verdict == ReviewVerdict.BLOCKED:
                if self._team_state["fix_round_count"] >= self.budget.max_fix_rounds:
                    stop_reason = TeamStopReason.BLOCKED
                    break

            # Start a new fix round.
            self._team_state["fix_round_count"] += 1
            fix_tasks = reviewer.create_fix_tasks(report.findings, all_tasks)
            if not fix_tasks:
                # No actionable blocker/high findings; treat as blocked.
                stop_reason = (
                    TeamStopReason.REFLECTION_LIMIT
                    if self._team_state["fix_round_count"] >= self.budget.max_fix_rounds
                    else TeamStopReason.BLOCKED
                )
                break

            emit_team_event(
                self._team_state,
                "team.fix_round_started",
                AgentRole.COORDINATOR.value,
                "root",
                fix_round=self._team_state["fix_round_count"],
                fix_task_count=len(fix_tasks),
            )
            all_tasks.extend(fix_tasks)
            completed_so_far = {tid for tid, r in all_results.items() if r.status == WorkerStatus.COMPLETED}
            round_results, round_statuses, stop_reason = self._execute_task_round(
                user_goal, fix_tasks, run_deadline, already_completed=completed_so_far
            )
            all_results.update(round_results)
            # If fix round itself did not complete, stop trying.
            if stop_reason != TeamStopReason.ALL_TASKS_COMPLETED:
                break

        summary = self._build_summary(stop_reason, all_results, review_findings)
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
            task_results=all_results,
            review_findings=review_findings,
            summary=summary,
            trace_events=list(self._team_state["trace_events"]),
        )

    def _execute_task_round(
        self,
        user_goal: str,
        tasks: list[AgentTask],
        run_deadline: float,
        already_completed: set[str] | None = None,
    ) -> tuple[dict[str, WorkerResult], dict[str, TaskStatus], TeamStopReason | None]:
        """Run one round of tasks to a terminal state.

        Returns the results, final statuses, and the stop reason. This helper is
        used for both the initial task set and subsequent Fix Task rounds.
        `already_completed` contains task ids from previous rounds that satisfy
        dependencies of tasks in this round.

        ``run_deadline`` is the absolute monotonic deadline shared across all
        rounds — it is NOT reset per round, so fix-review cycles cannot extend
        the team wall-time budget.
        """

        completed_ids = already_completed or set()
        results: dict[str, WorkerResult] = {}
        statuses: dict[str, TaskStatus] = {t.task_id: TaskStatus.PENDING for t in tasks}
        failed: set[str] = set()
        cancelled: set[str] = set()
        active_workers: dict[str, WorkerThread] = {}
        task_reserved_steps: dict[str, int] = {}
        task_reserved_model_calls: dict[str, int] = {}
        result_queue: Queue[tuple[str, WorkerResult]] = Queue()
        lock = threading.Lock()
        stop_reason: TeamStopReason | None = None

        def _dependency_satisfied(task_id: str) -> bool:
            if task_id in completed_ids:
                return True
            return statuses.get(task_id) == TaskStatus.COMPLETED

        while True:
            # Budget checks — wall time uses the absolute run deadline.
            if self._deadline_exceeded(run_deadline):
                stop_reason = TeamStopReason.BUDGET_EXHAUSTED
                break
            if self._team_steps_exhausted():
                emit_team_event(
                    self._team_state,
                    "team.budget_exhausted",
                    AgentRole.COORDINATOR.value,
                    "root",
                    reason="max_total_steps",
                    limit=self.budget.max_total_steps,
                    consumed=self._team_state["total_steps"],
                )
                stop_reason = TeamStopReason.BUDGET_EXHAUSTED
                break
            if self._team_model_calls_exhausted():
                emit_team_event(
                    self._team_state,
                    "team.budget_exhausted",
                    AgentRole.COORDINATOR.value,
                    "root",
                    reason="max_total_model_calls",
                    limit=self.budget.max_total_model_calls,
                    consumed=self._team_state["total_model_calls"],
                )
                stop_reason = TeamStopReason.BUDGET_EXHAUSTED
                break

            # Apply external cancellation requests before scheduling.
            with lock:
                for task in tasks:
                    if statuses[task.task_id] == TaskStatus.PENDING and self._is_task_cancelled(task.task_id):
                        statuses[task.task_id] = TaskStatus.CANCELLED
                        cancelled.add(task.task_id)
                for task_id, thread in list(active_workers.items()):
                    if self._is_task_cancelled(task_id) and thread.is_alive():
                        thread.result = self._cancel_active_worker(task_id, thread)

            # Schedule ready tasks. Pessimistically reserve both step and
            # model-call budgets so parallel scheduling does not overshoot the
            # team total. The model-call reservation uses max_steps as an upper
            # bound because each step makes at most one model call.
            with lock:
                for task in tasks:
                    if statuses[task.task_id] != TaskStatus.PENDING:
                        continue
                    if not all(_dependency_satisfied(dep) for dep in task.dependencies):
                        continue
                    if len(active_workers) >= self.budget.max_agents:
                        continue
                    capped_task = self._cap_task_to_remaining_budget(task)
                    model_call_bound = self._model_call_upper_bound(capped_task)
                    projected_steps = (
                        self._team_state["total_steps"]
                        + self._team_state["reserved_steps"]
                        + capped_task.max_steps
                    )
                    projected_model_calls = (
                        self._team_state["total_model_calls"]
                        + self._team_state["reserved_model_calls"]
                        + model_call_bound
                    )
                    if projected_steps > self.budget.max_total_steps:
                        statuses[task.task_id] = TaskStatus.CANCELLED
                        cancelled.add(task.task_id)
                        continue
                    if projected_model_calls > self.budget.max_total_model_calls:
                        statuses[task.task_id] = TaskStatus.CANCELLED
                        cancelled.add(task.task_id)
                        continue
                    statuses[task.task_id] = TaskStatus.RUNNING
                    self._team_state["reserved_steps"] += capped_task.max_steps
                    self._team_state["reserved_model_calls"] += model_call_bound
                    task_reserved_steps[task.task_id] = capped_task.max_steps
                    task_reserved_model_calls[task.task_id] = model_call_bound
                    worker = self._make_worker(f"worker-{len(active_workers)}")
                    thread = WorkerThread(worker, capped_task, self.workspace, result_queue)
                    active_workers[task.task_id] = thread
                    thread.start()

            # Collect finished Workers
            try:
                while True:
                    task_id, result = result_queue.get_nowait()
                    with lock:
                        active_workers.pop(task_id, None)
                        results[task_id] = result
                        self._team_state["reserved_steps"] -= task_reserved_steps.pop(
                            task_id, 0
                        )
                        self._team_state["reserved_model_calls"] -= task_reserved_model_calls.pop(
                            task_id, 0
                        )
                        self._accumulate_counters(result)
                        if result.status == WorkerStatus.COMPLETED:
                            statuses[task_id] = TaskStatus.COMPLETED
                        elif result.status == WorkerStatus.CANCELLED:
                            cancelled.add(task_id)
                            statuses[task_id] = TaskStatus.CANCELLED
                            # Cancel downstream tasks
                            self._cascade_cancel(task_id, tasks, statuses, cancelled)
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

        # Wait for any stragglers and cancel if needed. When the team stopped
        # because of budget exhaustion or an external cancellation, every active
        # Worker must be brought to a terminal state and its counters recorded.
        for task_id, thread in list(active_workers.items()):
            thread.join(timeout=5)
            if thread.is_alive():
                thread.result = self._cancel_active_worker(task_id, thread)
            results[task_id] = thread.result
            self._team_state["reserved_steps"] -= task_reserved_steps.pop(task_id, 0)
            self._team_state["reserved_model_calls"] -= task_reserved_model_calls.pop(task_id, 0)
            self._accumulate_counters(thread.result)
            statuses[task_id] = TaskStatus.CANCELLED

        # Mark any task that never started as blocked/cancelled so the final
        # state is fully terminal.
        for task in tasks:
            if statuses[task.task_id] == TaskStatus.PENDING:
                if stop_reason == TeamStopReason.BUDGET_EXHAUSTED:
                    statuses[task.task_id] = TaskStatus.CANCELLED
                elif stop_reason == TeamStopReason.CANCELLED:
                    statuses[task.task_id] = TaskStatus.CANCELLED
                else:
                    statuses[task.task_id] = TaskStatus.BLOCKED

        # Ensure every terminal task has a WorkerResult in the returned map.
        for task in tasks:
            if statuses.get(task.task_id) == TaskStatus.CANCELLED and task.task_id not in results:
                results[task.task_id] = WorkerResult(
                    task_id=task.task_id,
                    status=WorkerStatus.CANCELLED,
                    summary="cancelled before execution",
                )

        return results, statuses, stop_reason

    def _make_worker(self, agent_id: str) -> Worker:
        return Worker(
            agent_id=agent_id,
            model=self._model_factory(agent_id),
            guard=self._guard,
            lease_manager=self._lease_manager,
            team_state=self._team_state,
            enable_verification_gate=self.enable_verification_gate,
        )

    def _deadline_exceeded(self, run_deadline: float) -> bool:
        """Check if the absolute wall-clock deadline has been reached.

        The deadline is set once at the start of ``_run_parallel`` and shared
        across all fix-review rounds. This prevents each round from resetting
        the timer and silently exceeding the team wall-time budget.
        """

        return time.monotonic() > run_deadline

    def _team_steps_exhausted(self) -> bool:
        """True when the aggregated step count reaches the team limit."""

        return self._team_state["total_steps"] >= self.budget.max_total_steps

    def _team_model_calls_exhausted(self) -> bool:
        """True when the aggregated model-call count reaches the team limit."""

        return self._team_state["total_model_calls"] >= self.budget.max_total_model_calls

    def _cap_task_to_remaining_budget(self, task: AgentTask) -> AgentTask:
        """Return a task copy whose max_steps does not exceed the remaining team budget.

        This prevents a single Worker from consuming the entire team step budget
        and leaves headroom for other tasks. Model-call budgets cannot be capped
        ahead of time because they depend on runtime reflection; they are checked
        after each Worker finishes.
        """

        remaining_steps = max(0, self.budget.max_total_steps - self._team_state["total_steps"])
        if task.max_steps > remaining_steps:
            return replace(task, max_steps=max(1, remaining_steps))
        return task

    # Conservative upper bound on reflection rounds per run. Matches the
    # hardcoded default in agent/state.py initial_state. When the verification
    # gate is enabled, each done proposal can trigger up to this many extra
    # model calls (one per reflection round). Reserving only max_steps would
    # allow parallel Workers to overshoot max_total_model_calls.
    _REFLECTION_RESERVE = 2

    def _model_call_upper_bound(self, task: AgentTask) -> int:
        """Conservative upper bound on model calls one task can consume.

        Each step makes at most one decide model call. With the verification
        gate enabled, a done proposal can trigger up to ``_REFLECTION_RESERVE``
        additional reflection model calls. We reserve both to prevent parallel
        scheduling from overshooting ``max_total_model_calls``.

        Without this padding, a task with ``max_steps=1`` and
        ``max_total_model_calls=1`` could actually consume 2 model calls
        (1 decide + 1 reflect), silently breaking the budget guarantee.
        """

        bound = task.max_steps
        if self.enable_verification_gate:
            bound += self._REFLECTION_RESERVE
        return bound

    def _accumulate_counters(self, result: WorkerResult) -> None:
        """Add a Worker's consumed resources to the team totals."""

        self._team_state["total_steps"] += result.step_count
        self._team_state["total_model_calls"] += result.model_call_count
        self._team_state["total_tool_calls"] += result.tool_call_count

    def _cascade_cancel(
        self,
        cancelled_task_id: str,
        tasks: list[AgentTask],
        statuses: dict[str, TaskStatus],
        cancelled: set[str],
    ) -> None:
        """Mark every dependent task as cancelled when its ancestor is cancelled."""

        dependents: dict[str, list[str]] = {t.task_id: [] for t in tasks}
        for task in tasks:
            for dep in task.dependencies:
                if dep in dependents:
                    dependents[dep].append(task.task_id)
        stack = [cancelled_task_id]
        while stack:
            current = stack.pop()
            for dependent in dependents.get(current, []):
                if statuses.get(dependent) == TaskStatus.PENDING:
                    statuses[dependent] = TaskStatus.CANCELLED
                    cancelled.add(dependent)
                    stack.append(dependent)

    def _cancel_active_worker(self, task_id: str, thread: WorkerThread) -> WorkerResult:
        """Signal cancellation to a running Worker and wait for it to stop.

        The Worker's ``cancel()`` method kills any running subprocesses and
        sets the cooperative cancel event. Leases are NOT released by
        ``cancel()`` — they are released by ``Worker.run()`` when the runtime
        naturally exits. This method waits up to 10 seconds for that to happen.

        If the thread does not terminate within the timeout, the result is
        marked ``unknown_outcome`` because we cannot guarantee the Worker has
        stopped producing side effects. The leases remain held until the thread
        eventually finishes, preventing another Worker from writing to the same
        files while the old process might still be active.
        """

        thread.worker.cancel(thread.task)
        thread.join(timeout=10)
        if thread.is_alive():
            emit_team_event(
                self._team_state,
                "worker.cancel_failed",
                thread.worker.agent_id,
                task_id,
                reason="thread did not terminate after cooperative cancel and process kill",
            )
            return WorkerResult(
                task_id=task_id,
                status=WorkerStatus.CANCELLED,
                summary="unknown_outcome: worker thread did not terminate within timeout; leases remain held",
            )
        # Thread finished — Worker.run() has already released leases.
        if thread.result and thread.result.status == WorkerStatus.COMPLETED:
            return thread.result
        return WorkerResult(
            task_id=task_id,
            status=WorkerStatus.CANCELLED,
            summary="cancelled by coordinator",
        )

    def cancel(self, task_id: str, tasks: list[AgentTask]) -> None:
        """Request cancellation of a task and cascade to all dependents.

        This is the entry point for parent-task cancellation (M-07). The running
        Coordinator loop checks the cancelled set before scheduling new tasks and
        signals active Workers to stop. Pending dependents are marked cancelled
        in the next scheduling tick.
        """

        emit_team_event(
            self._team_state,
            "cancel.requested",
            AgentRole.COORDINATOR.value,
            task_id,
            reason="parent task cancelled",
        )
        with self._cancel_lock:
            cancelled: set[str] = {task_id}
            statuses: dict[str, TaskStatus] = {t.task_id: TaskStatus.PENDING for t in tasks}
            statuses[task_id] = TaskStatus.CANCELLED
            self._cascade_cancel(task_id, tasks, statuses, cancelled)
            self._cancelled_task_ids.update(cancelled)

    def _is_task_cancelled(self, task_id: str) -> bool:
        with self._cancel_lock:
            return task_id in self._cancelled_task_ids

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
            f"findings={len(findings)}, fix_rounds={self._team_state['fix_round_count']}, "
            f"steps={self._team_state['total_steps']}/{self.budget.max_total_steps}, "
            f"model_calls={self._team_state['total_model_calls']}/{self.budget.max_total_model_calls}"
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
