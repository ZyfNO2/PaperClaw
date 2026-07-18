"""Distributed ownership seam and fenced SQLite reference implementation.

SQLite here proves cross-process contention on one shared database file. It is
not advertised as a multi-host database. The ownership contract is transport /
backend neutral so a later external shared-store adapter can implement the same
fencing semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .contracts import (
    TaskEvent,
    TaskExecutionResult,
    TaskLeaseError,
    TaskRecord,
    TaskSpec,
    TaskStatus,
    TaskTransitionError,
)
from .store import SQLiteDurableTaskStore, _identifier, _json_dump, _required_text


@dataclass(frozen=True)
class TaskLease:
    task: TaskRecord
    worker_id: str
    generation: int

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise ValueError("worker_id must not be empty")
        if isinstance(self.generation, bool) or self.generation < 1:
            raise ValueError("generation must be a positive integer")
        if self.task.lease_owner != self.worker_id:
            raise ValueError("lease worker must match task lease owner")


class DurableTaskStore(Protocol):
    """Backend-neutral durable task store surface consumed by runtime/tools."""

    def create_task(self, spec: TaskSpec) -> tuple[TaskRecord, bool]: ...
    def get_task(self, task_id: str) -> TaskRecord: ...
    def list_tasks(
        self,
        *,
        parent_run_id: str | None = None,
        statuses: Sequence[TaskStatus | str] | None = None,
        limit: int = 200,
    ) -> tuple[TaskRecord, ...]: ...
    def refresh_dependencies(self) -> tuple[str, ...]: ...
    def request_cancel(self, task_id: str, *, reason: str) -> TaskRecord: ...
    def recover_expired_leases(self) -> tuple[TaskRecord, ...]: ...
    def list_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> tuple[TaskEvent, ...]: ...


class FencedDurableTaskStore(DurableTaskStore, Protocol):
    def claim_next_lease(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 30.0,
    ) -> TaskLease | None: ...

    def start_task_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
    ) -> TaskRecord: ...

    def heartbeat_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
        lease_seconds: float = 30.0,
    ) -> TaskRecord: ...

    def mark_side_effect_state_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
        state: str,
    ) -> TaskRecord: ...

    def complete_task_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
        result: TaskExecutionResult,
    ) -> TaskRecord: ...

    def requeue_task_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
        reason: str,
    ) -> TaskRecord: ...


class FencedSQLiteDurableTaskStore(SQLiteDurableTaskStore):
    """SQLite reference store with monotonic lease-generation fencing."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._initialize_fencing()

    def claim_next_lease(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 30.0,
    ) -> TaskLease | None:
        worker = _identifier(worker_id, "worker_id")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.refresh_dependencies()
        now = self._clock()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM background_tasks
                WHERE status = 'queued' AND cancel_requested = 0
                ORDER BY created_at, task_id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            task_id = row["task_id"]
            version = int(row["version"])
            if int(row["attempt"]) >= int(row["max_attempts"]):
                self._transition_locked(
                    connection,
                    task_id,
                    TaskStatus.QUEUED,
                    TaskStatus.FAILED,
                    "attempt_budget_exhausted",
                    now,
                )
                return None

            generation_row = connection.execute(
                "SELECT generation FROM background_task_fencing WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            generation = (
                int(generation_row["generation"]) + 1
                if generation_row is not None
                else 1
            )
            connection.execute(
                """
                INSERT INTO background_task_fencing(task_id, generation, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    generation = excluded.generation,
                    updated_at = excluded.updated_at
                """,
                (task_id, generation, now),
            )
            cursor = connection.execute(
                """
                UPDATE background_tasks
                SET status = 'claimed', version = version + 1,
                    attempt = attempt + 1, lease_owner = ?,
                    lease_expires_at = ?, last_heartbeat_at = ?, updated_at = ?
                WHERE task_id = ? AND status = 'queued' AND version = ?
                """,
                (worker, now + lease_seconds, now, now, task_id, version),
            )
            if cursor.rowcount != 1:
                raise TaskLeaseError("queued task changed during fenced claim")
            self._append_event(
                connection,
                task_id,
                "task.claimed",
                {
                    "worker_id": worker,
                    "attempt": int(row["attempt"]) + 1,
                    "lease_generation": generation,
                },
                now,
            )
            task = self._get_task(connection, task_id)
            return TaskLease(task, worker, generation)

    def start_task_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
    ) -> TaskRecord:
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_fenced_owner(
                connection, task, worker_id, expected_version, lease_generation
            )
            if task.status is not TaskStatus.CLAIMED:
                raise TaskTransitionError("only claimed tasks can start")
            cursor = connection.execute(
                """
                UPDATE background_tasks
                SET status = 'running', version = version + 1,
                    started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE task_id = ? AND status = 'claimed' AND version = ?
                  AND lease_owner = ?
                """,
                (now, now, task.task_id, expected_version, worker_id),
            )
            if cursor.rowcount != 1:
                raise TaskLeaseError("task changed before fenced start")
            self._append_event(
                connection,
                task.task_id,
                "task.started",
                {
                    "worker_id": worker_id,
                    "attempt": task.attempt,
                    "lease_generation": lease_generation,
                },
                now,
            )
            return self._get_task(connection, task.task_id)

    def heartbeat_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
        lease_seconds: float = 30.0,
    ) -> TaskRecord:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_fenced_owner(
                connection, task, worker_id, expected_version, lease_generation
            )
            if task.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
                raise TaskLeaseError("task is not active")
            cursor = connection.execute(
                """
                UPDATE background_tasks
                SET lease_expires_at = ?, last_heartbeat_at = ?, updated_at = ?
                WHERE task_id = ? AND lease_owner = ? AND version = ?
                """,
                (
                    now + lease_seconds,
                    now,
                    now,
                    task.task_id,
                    worker_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskLeaseError("fenced heartbeat lost ownership")
            return self._get_task(connection, task.task_id)

    def mark_side_effect_state_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
        state: str,
    ) -> TaskRecord:
        normalized = _required_text(state, "side_effect_state")
        if normalized not in {"none", "safe", "committed", "unknown"}:
            raise ValueError("unsupported side_effect_state")
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_fenced_owner(
                connection, task, worker_id, expected_version, lease_generation
            )
            cursor = connection.execute(
                """
                UPDATE background_tasks SET side_effect_state = ?, updated_at = ?
                WHERE task_id = ? AND lease_owner = ? AND version = ?
                """,
                (normalized, now, task.task_id, worker_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise TaskLeaseError("fenced side-effect update lost ownership")
            return self._get_task(connection, task.task_id)

    def complete_task_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
        result: TaskExecutionResult,
    ) -> TaskRecord:
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_fenced_owner(
                connection, task, worker_id, expected_version, lease_generation
            )
            if task.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
                raise TaskTransitionError("task is not active")
            # Reuse the existing transition policy by delegating validation to the
            # base implementation's public rules, but perform the write here so
            # generation and ownership stay in one transaction.
            allowed = {
                TaskStatus.CLAIMED: {
                    TaskStatus.RUNNING,
                    TaskStatus.QUEUED,
                    TaskStatus.CANCELLED,
                    TaskStatus.UNKNOWN_OUTCOME,
                },
                TaskStatus.RUNNING: {
                    TaskStatus.QUEUED,
                    TaskStatus.SUCCEEDED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.TIMED_OUT,
                    TaskStatus.UNKNOWN_OUTCOME,
                },
            }
            if result.status not in allowed[task.status]:
                raise TaskTransitionError(
                    f"transition not allowed: {task.status.value} -> {result.status.value}"
                )
            cursor = connection.execute(
                """
                UPDATE background_tasks
                SET status = ?, version = version + 1, updated_at = ?,
                    completed_at = ?, stop_reason = ?, output_json = ?,
                    error_json = ?, side_effect_state = ?, lease_owner = NULL,
                    lease_expires_at = NULL, last_heartbeat_at = NULL
                WHERE task_id = ? AND status = ? AND version = ? AND lease_owner = ?
                """,
                (
                    result.status.value,
                    now,
                    now,
                    result.stop_reason,
                    _json_dump(result.output) if result.output is not None else None,
                    _json_dump(result.error) if result.error is not None else None,
                    result.side_effect_state,
                    task.task_id,
                    task.status.value,
                    expected_version,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskLeaseError("fenced completion lost ownership")
            self._append_event(
                connection,
                task.task_id,
                f"task.{result.status.value}",
                {
                    "stop_reason": result.stop_reason,
                    "model_calls": result.model_calls,
                    "tool_calls": result.tool_calls,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "side_effect_state": result.side_effect_state,
                    "lease_generation": lease_generation,
                },
                now,
            )
            self.refresh_dependencies_after(connection, task.task_id, now)
            return self._get_task(connection, task.task_id)

    def requeue_task_fenced(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_generation: int,
        reason: str,
    ) -> TaskRecord:
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_fenced_owner(
                connection, task, worker_id, expected_version, lease_generation
            )
            if task.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
                raise TaskTransitionError("task is not active")
            if task.attempt >= task.max_attempts:
                raise TaskTransitionError("attempt budget exhausted")
            if task.side_effect_state not in {"none", "safe"}:
                raise TaskTransitionError("task with uncertain side effects cannot retry")
            cursor = connection.execute(
                """
                UPDATE background_tasks
                SET status = 'queued', version = version + 1, updated_at = ?,
                    stop_reason = ?, lease_owner = NULL, lease_expires_at = NULL,
                    last_heartbeat_at = NULL
                WHERE task_id = ? AND status = ? AND version = ? AND lease_owner = ?
                """,
                (
                    now,
                    _required_text(reason, "reason")[:500],
                    task.task_id,
                    task.status.value,
                    expected_version,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskLeaseError("fenced requeue lost ownership")
            self._append_event(
                connection,
                task.task_id,
                "task.queued",
                {
                    "reason": reason,
                    "attempt": task.attempt,
                    "lease_generation": lease_generation,
                },
                now,
            )
            return self._get_task(connection, task.task_id)

    def current_lease_generation(self, task_id: str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT generation FROM background_task_fencing WHERE task_id = ?",
                (_identifier(task_id, "task_id"),),
            ).fetchone()
            return int(row["generation"]) if row is not None else 0

    def _assert_fenced_owner(
        self,
        connection,
        task: TaskRecord,
        worker_id: str,
        expected_version: int,
        lease_generation: int,
    ) -> None:
        if isinstance(lease_generation, bool) or lease_generation < 1:
            raise TaskLeaseError("lease generation must be positive")
        self._assert_owner(task, worker_id, expected_version)
        row = connection.execute(
            "SELECT generation FROM background_task_fencing WHERE task_id = ?",
            (task.task_id,),
        ).fetchone()
        current = int(row["generation"]) if row is not None else 0
        if current != lease_generation:
            raise TaskLeaseError(
                f"stale lease generation: expected current {current}, got {lease_generation}"
            )

    def _initialize_fencing(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS background_task_fencing (
                    task_id TEXT PRIMARY KEY REFERENCES background_tasks(task_id),
                    generation INTEGER NOT NULL CHECK(generation >= 1),
                    updated_at REAL NOT NULL
                );
                """
            )


__all__ = [
    "DurableTaskStore",
    "FencedDurableTaskStore",
    "FencedSQLiteDurableTaskStore",
    "TaskLease",
]
