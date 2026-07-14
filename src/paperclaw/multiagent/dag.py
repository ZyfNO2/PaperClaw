"""Task DAG validation for the Coordinator.

The DAG must be acyclic, fully connected, and free of write conflicts before any
Worker is scheduled. Validation failures are deterministic and do not depend on
model output.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperclaw.multiagent.contracts import AgentTask, TaskStatus


@dataclass
class DAGValidation:
    """Result of validating a candidate task DAG."""

    valid: bool
    errors: list[str]
    topological_order: list[str] | None = None


def validate_task_dag(tasks: list[AgentTask]) -> DAGValidation:
    """Check that a list of tasks forms a valid, executable DAG.

    Rules from SOP v0.03:
    - No cycles.
    - Every dependency references an existing task_id.
    - Writable paths do not conflict across tasks that may run in parallel.
    - Every leaf task has at least one acceptance criterion.
    - Every task has a positive budget and timeout.
    - There is at least one terminal task (no task depends on it).
    """

    errors: list[str] = []
    task_by_id: dict[str, AgentTask] = {}
    for task in tasks:
        if task.task_id in task_by_id:
            errors.append(f"duplicate task_id: {task.task_id}")
        task_by_id[task.task_id] = task

    # Dependency existence
    for task in tasks:
        for dep in task.dependencies:
            if dep not in task_by_id:
                errors.append(f"task {task.task_id} depends on unknown task {dep}")

    # Cycle detection via Kahn's algorithm; also gives a topological order.
    in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
    dependents: dict[str, list[str]] = {t.task_id: [] for t in tasks}
    for task in tasks:
        for dep in task.dependencies:
            if dep in dependents:
                dependents[dep].append(task.task_id)
                in_degree[task.task_id] += 1

    queue: deque[str] = deque([tid for tid, deg in in_degree.items() if deg == 0])
    topo: list[str] = []
    while queue:
        current = queue.popleft()
        topo.append(current)
        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(topo) != len(tasks):
        unresolved = sorted(tid for tid, deg in in_degree.items() if deg > 0)
        errors.append(f"cycle detected involving tasks: {', '.join(unresolved)}")

    # Per-task sanity
    for task in tasks:
        if not task.acceptance_criteria:
            errors.append(f"task {task.task_id} has no acceptance criteria")
        if task.max_steps < 1:
            errors.append(f"task {task.task_id} max_steps must be positive")
        if task.timeout_seconds < 1:
            errors.append(f"task {task.task_id} timeout_seconds must be positive")

    # Write conflict detection: two tasks that claim the same concrete output
    # file and are not ordered by dependency are unsafe to run in parallel.
    # Writable directories (e.g. "src") are intentionally shared; file-level
    # exclusivity is enforced at runtime by LeaseManager.
    def _concrete_writable_paths(task: AgentTask) -> set[str]:
        concrete: set[str] = set()
        for path in task.writable_paths:
            p = Path(path)
            # Treat paths with a file extension or explicit filename as concrete.
            if p.suffix or (p.name and "." in p.name):
                concrete.add(str(p.as_posix()))
        concrete.update(task.expected_artifacts)
        return concrete

    writable_sets: dict[str, set[str]] = {task.task_id: _concrete_writable_paths(task) for task in tasks}

    for i, t_a in enumerate(tasks):
        for t_b in tasks[i + 1 :]:
            overlap = writable_sets[t_a.task_id] & writable_sets[t_b.task_id]
            if not overlap:
                continue
            # Ordered by dependency already? Check reachability in topo.
            a_before_b = _reachable(t_a.task_id, t_b.task_id, dependents)
            b_before_a = _reachable(t_b.task_id, t_a.task_id, dependents)
            if not a_before_b and not b_before_a:
                errors.append(
                    f"writable path conflict between {t_a.task_id} and {t_b.task_id}: "
                    f"{', '.join(sorted(overlap))}"
                )

    # At least one terminal task
    terminal = [tid for tid in task_by_id if not dependents[tid]]
    if not terminal and tasks:
        errors.append("DAG has no terminal task")

    if errors:
        return DAGValidation(valid=False, errors=errors)
    return DAGValidation(valid=True, errors=[], topological_order=topo)


def _reachable(start: str, target: str, dependents: dict[str, list[str]]) -> bool:
    """Return True if any path from start reaches target in the dependency graph."""

    visited: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(dependents.get(current, []))
    return False


def compute_task_status(tasks: list[AgentTask], results: dict[str, Any]) -> dict[str, TaskStatus]:
    """Compute the status of every task from completed results.

    A task is READY when all dependencies have COMPLETED status; otherwise it is
    PENDING. This is a deterministic helper used by the Coordinator scheduler.
    """

    status: dict[str, TaskStatus] = {}
    for task in tasks:
        if task.task_id in results:
            status[task.task_id] = TaskStatus.COMPLETED
        elif all(dep in status and status[dep] == TaskStatus.COMPLETED for dep in task.dependencies):
            status[task.task_id] = TaskStatus.READY
        else:
            status[task.task_id] = TaskStatus.PENDING
    return status
