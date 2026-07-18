"""SQLite fact store for durable background tasks, leases, events and output."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Iterator, Mapping, Sequence

from .contracts import (
    TERMINAL_TASK_STATUSES,
    TaskConflictError,
    TaskEvent,
    TaskExecutionResult,
    TaskLeaseError,
    TaskNotFoundError,
    TaskRecord,
    TaskSpec,
    TaskStatus,
    TaskTransitionError,
)

_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset(
        {TaskStatus.QUEUED, TaskStatus.WAITING_DEPENDENCY, TaskStatus.CANCELLED}
    ),
    TaskStatus.WAITING_DEPENDENCY: frozenset(
        {TaskStatus.QUEUED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.QUEUED: frozenset(
        {TaskStatus.CLAIMED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
    ),
    TaskStatus.CLAIMED: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.QUEUED,
            TaskStatus.CANCELLED,
            TaskStatus.UNKNOWN_OUTCOME,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.QUEUED,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMED_OUT,
            TaskStatus.UNKNOWN_OUTCOME,
        }
    ),
}
for _status in TERMINAL_TASK_STATUSES:
    _ALLOWED_TRANSITIONS.setdefault(_status, frozenset())


class SQLiteDurableTaskStore:
    """Single-node durable queue with optimistic transitions and worker leases."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        if not self.path.parent.exists():
            raise ValueError("database parent directory must exist")
        self._clock = clock
        self._initialize()

    def create_task(self, spec: TaskSpec) -> tuple[TaskRecord, bool]:
        normalized = _validate_spec(spec)
        digest = _spec_digest(normalized)
        now = self._clock()
        initial = (
            TaskStatus.WAITING_DEPENDENCY
            if normalized.dependencies
            else TaskStatus.QUEUED
        )
        with self._transaction() as connection:
            if normalized.idempotency_key:
                row = connection.execute(
                    "SELECT request_digest, task_id FROM background_task_idempotency "
                    "WHERE idempotency_key = ?",
                    (normalized.idempotency_key,),
                ).fetchone()
                if row is not None:
                    if row["request_digest"] != digest:
                        raise TaskConflictError(
                            "idempotency key belongs to another task request"
                        )
                    return self._get_task(connection, row["task_id"]), False

            for dependency in normalized.dependencies:
                if connection.execute(
                    "SELECT 1 FROM background_tasks WHERE task_id = ?",
                    (dependency,),
                ).fetchone() is None:
                    raise TaskNotFoundError(f"unknown dependency: {dependency}")
            try:
                connection.execute(
                    """
                    INSERT INTO background_tasks (
                        task_id, parent_run_id, request_digest, objective, workspace,
                        status, version, attempt, max_attempts, max_steps,
                        timeout_seconds, cancel_requested, lease_owner,
                        lease_expires_at, last_heartbeat_at, side_effect_state,
                        created_at, updated_at, started_at, completed_at,
                        stop_reason, output_json, error_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, 0, NULL, NULL,
                              NULL, 'none', ?, ?, NULL, NULL, NULL, NULL, NULL, ?)
                    """,
                    (
                        normalized.task_id,
                        normalized.parent_run_id,
                        digest,
                        normalized.objective,
                        normalized.workspace,
                        initial.value,
                        normalized.max_attempts,
                        normalized.max_steps,
                        normalized.timeout_seconds,
                        now,
                        now,
                        _json_dump(normalized.metadata),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise TaskConflictError(
                    f"task already exists: {normalized.task_id}"
                ) from exc

            connection.executemany(
                "INSERT INTO background_task_dependencies(task_id, depends_on) "
                "VALUES (?, ?)",
                [(normalized.task_id, value) for value in normalized.dependencies],
            )
            if normalized.idempotency_key:
                connection.execute(
                    """
                    INSERT INTO background_task_idempotency(
                        idempotency_key, request_digest, task_id, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        normalized.idempotency_key,
                        digest,
                        normalized.task_id,
                        now,
                    ),
                )
            self._append_event(
                connection,
                normalized.task_id,
                "task.created",
                {
                    "status": initial.value,
                    "dependencies": list(normalized.dependencies),
                },
                now,
            )
            if initial is TaskStatus.QUEUED:
                self._append_event(
                    connection,
                    normalized.task_id,
                    "task.queued",
                    {"reason": "no_dependencies"},
                    now,
                )
            return self._get_task(connection, normalized.task_id), True

    def get_task(self, task_id: str) -> TaskRecord:
        with self._connection() as connection:
            return self._get_task(connection, _identifier(task_id, "task_id"))

    def list_tasks(
        self,
        *,
        parent_run_id: str | None = None,
        statuses: Sequence[TaskStatus | str] | None = None,
        limit: int = 200,
    ) -> tuple[TaskRecord, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 1_000:
            raise ValueError("limit must be within [1, 1000]")
        clauses: list[str] = []
        values: list[Any] = []
        if parent_run_id is not None:
            clauses.append("parent_run_id = ?")
            values.append(_identifier(parent_run_id, "parent_run_id"))
        if statuses:
            normalized = [TaskStatus(value).value for value in statuses]
            clauses.append("status IN (%s)" % ",".join("?" for _ in normalized))
            values.extend(normalized)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM background_tasks {where} "
                "ORDER BY created_at, task_id LIMIT ?",
                values,
            ).fetchall()
            return tuple(self._row_to_task(connection, row) for row in rows)

    def refresh_dependencies(self) -> tuple[str, ...]:
        now = self._clock()
        changed: list[str] = []
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT task_id FROM background_tasks "
                "WHERE status = 'waiting_dependency' ORDER BY created_at, task_id"
            ).fetchall()
            for row in rows:
                task_id = row["task_id"]
                statuses = [
                    TaskStatus(value["status"])
                    for value in connection.execute(
                        """
                        SELECT dependency.status
                        FROM background_task_dependencies AS edge
                        JOIN background_tasks AS dependency
                          ON dependency.task_id = edge.depends_on
                        WHERE edge.task_id = ?
                        ORDER BY edge.depends_on
                        """,
                        (task_id,),
                    ).fetchall()
                ]
                if any(
                    status in TERMINAL_TASK_STATUSES
                    and status is not TaskStatus.SUCCEEDED
                    for status in statuses
                ):
                    self._transition_locked(
                        connection,
                        task_id,
                        TaskStatus.WAITING_DEPENDENCY,
                        TaskStatus.BLOCKED,
                        "dependency_failed",
                        now,
                    )
                    changed.append(task_id)
                elif statuses and all(
                    status is TaskStatus.SUCCEEDED for status in statuses
                ):
                    self._transition_locked(
                        connection,
                        task_id,
                        TaskStatus.WAITING_DEPENDENCY,
                        TaskStatus.QUEUED,
                        "dependencies_satisfied",
                        now,
                    )
                    changed.append(task_id)
        return tuple(changed)

    def claim_next(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 30.0,
    ) -> TaskRecord | None:
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
                raise TaskConflictError("queued task changed during claim")
            self._append_event(
                connection,
                task_id,
                "task.claimed",
                {"worker_id": worker, "attempt": int(row["attempt"]) + 1},
                now,
            )
            return self._get_task(connection, task_id)

    def start_task(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
    ) -> TaskRecord:
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_owner(task, worker_id, expected_version)
            if task.status is not TaskStatus.CLAIMED:
                raise TaskTransitionError("only claimed tasks can start")
            cursor = connection.execute(
                """
                UPDATE background_tasks
                SET status = 'running', version = version + 1,
                    started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE task_id = ? AND status = 'claimed' AND version = ?
                """,
                (now, now, task.task_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise TaskConflictError("task changed before start")
            self._append_event(
                connection,
                task.task_id,
                "task.started",
                {"worker_id": worker_id, "attempt": task.attempt},
                now,
            )
            return self._get_task(connection, task.task_id)

    def heartbeat(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_seconds: float = 30.0,
    ) -> TaskRecord:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_owner(task, worker_id, expected_version)
            if task.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
                raise TaskLeaseError("task is not active")
            connection.execute(
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
            return self._get_task(connection, task.task_id)

    def mark_side_effect_state(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        state: str,
    ) -> TaskRecord:
        normalized = _required_text(state, "side_effect_state")
        if normalized not in {"none", "safe", "committed", "unknown"}:
            raise ValueError("unsupported side_effect_state")
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_owner(task, worker_id, expected_version)
            connection.execute(
                "UPDATE background_tasks SET side_effect_state = ?, updated_at = ? "
                "WHERE task_id = ? AND lease_owner = ? AND version = ?",
                (normalized, self._clock(), task.task_id, worker_id, expected_version),
            )
            return self._get_task(connection, task.task_id)

    def request_cancel(self, task_id: str, *, reason: str) -> TaskRecord:
        normalized_reason = _required_text(reason, "reason")[:500]
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            if task.terminal:
                return task
            if task.status in {
                TaskStatus.CREATED,
                TaskStatus.WAITING_DEPENDENCY,
                TaskStatus.QUEUED,
                TaskStatus.CLAIMED,
            }:
                self._transition_locked(
                    connection,
                    task.task_id,
                    task.status,
                    TaskStatus.CANCELLED,
                    normalized_reason,
                    now,
                )
            else:
                connection.execute(
                    "UPDATE background_tasks SET cancel_requested = 1, "
                    "stop_reason = ?, updated_at = ? WHERE task_id = ?",
                    (normalized_reason, now, task.task_id),
                )
                self._append_event(
                    connection,
                    task.task_id,
                    "task.cancel_requested",
                    {"reason": normalized_reason},
                    now,
                )
            return self._get_task(connection, task.task_id)

    def complete_task(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        result: TaskExecutionResult,
    ) -> TaskRecord:
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_owner(task, worker_id, expected_version)
            if task.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
                raise TaskTransitionError("task is not active")
            if result.status not in _ALLOWED_TRANSITIONS[task.status]:
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
                raise TaskConflictError("task completion lost ownership")
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
                },
                now,
            )
            self.refresh_dependencies_after(connection, task.task_id, now)
            return self._get_task(connection, task.task_id)

    def requeue_task(
        self,
        task_id: str,
        worker_id: str,
        *,
        expected_version: int,
        reason: str,
    ) -> TaskRecord:
        now = self._clock()
        with self._transaction() as connection:
            task = self._get_task(connection, task_id)
            self._assert_owner(task, worker_id, expected_version)
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
                raise TaskConflictError("task requeue lost ownership")
            self._append_event(
                connection,
                task.task_id,
                "task.queued",
                {"reason": reason, "attempt": task.attempt},
                now,
            )
            return self._get_task(connection, task.task_id)

    def recover_expired_leases(self) -> tuple[TaskRecord, ...]:
        now = self._clock()
        recovered: list[TaskRecord] = []
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM background_tasks
                WHERE status IN ('claimed', 'running')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                ORDER BY updated_at, task_id
                """,
                (now,),
            ).fetchall()
            for row in rows:
                task = self._row_to_task(connection, row)
                if task.side_effect_state in {"committed", "unknown"}:
                    next_status = TaskStatus.UNKNOWN_OUTCOME
                    reason = "lease_expired_after_possible_side_effect"
                elif task.attempt < task.max_attempts:
                    next_status = TaskStatus.QUEUED
                    reason = "lease_expired_requeued"
                else:
                    next_status = TaskStatus.FAILED
                    reason = "lease_expired_attempt_budget_exhausted"
                connection.execute(
                    """
                    UPDATE background_tasks
                    SET status = ?, version = version + 1, updated_at = ?,
                        completed_at = CASE WHEN ? IN ('failed','unknown_outcome')
                                            THEN ? ELSE completed_at END,
                        stop_reason = ?, lease_owner = NULL,
                        lease_expires_at = NULL, last_heartbeat_at = NULL
                    WHERE task_id = ? AND version = ?
                    """,
                    (
                        next_status.value,
                        now,
                        next_status.value,
                        now,
                        reason,
                        task.task_id,
                        task.version,
                    ),
                )
                self._append_event(
                    connection,
                    task.task_id,
                    f"task.{next_status.value}",
                    {"reason": reason, "recovered": True},
                    now,
                )
                recovered.append(self._get_task(connection, task.task_id))
        return tuple(recovered)

    def list_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> tuple[TaskEvent, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        if isinstance(limit, bool) or not 1 <= limit <= 5_000:
            raise ValueError("limit must be within [1, 5000]")
        self.get_task(task_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM background_task_events
                WHERE task_id = ? AND sequence > ?
                ORDER BY sequence LIMIT ?
                """,
                (task_id, after_sequence, limit),
            ).fetchall()
            return tuple(
                TaskEvent(
                    task_id=row["task_id"],
                    sequence=int(row["sequence"]),
                    event_type=row["event_type"],
                    payload=json.loads(row["payload_json"]),
                    timestamp=float(row["timestamp"]),
                )
                for row in rows
            )

    def refresh_dependencies_after(
        self,
        connection: sqlite3.Connection,
        completed_task_id: str,
        now: float,
    ) -> None:
        dependents = connection.execute(
            "SELECT task_id FROM background_task_dependencies WHERE depends_on = ?",
            (completed_task_id,),
        ).fetchall()
        for row in dependents:
            task_id = row["task_id"]
            task_row = connection.execute(
                "SELECT status FROM background_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task_row is None or task_row["status"] != TaskStatus.WAITING_DEPENDENCY.value:
                continue
            statuses = [
                TaskStatus(value["status"])
                for value in connection.execute(
                    """
                    SELECT dependency.status
                    FROM background_task_dependencies AS edge
                    JOIN background_tasks AS dependency
                      ON dependency.task_id = edge.depends_on
                    WHERE edge.task_id = ?
                    """,
                    (task_id,),
                ).fetchall()
            ]
            if any(
                status in TERMINAL_TASK_STATUSES
                and status is not TaskStatus.SUCCEEDED
                for status in statuses
            ):
                self._transition_locked(
                    connection,
                    task_id,
                    TaskStatus.WAITING_DEPENDENCY,
                    TaskStatus.BLOCKED,
                    "dependency_failed",
                    now,
                )
            elif statuses and all(status is TaskStatus.SUCCEEDED for status in statuses):
                self._transition_locked(
                    connection,
                    task_id,
                    TaskStatus.WAITING_DEPENDENCY,
                    TaskStatus.QUEUED,
                    "dependencies_satisfied",
                    now,
                )

    def _transition_locked(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        expected: TaskStatus,
        next_status: TaskStatus,
        reason: str,
        now: float,
    ) -> None:
        if next_status not in _ALLOWED_TRANSITIONS[expected]:
            raise TaskTransitionError(
                f"transition not allowed: {expected.value} -> {next_status.value}"
            )
        terminal = next_status in TERMINAL_TASK_STATUSES
        cursor = connection.execute(
            """
            UPDATE background_tasks
            SET status = ?, version = version + 1, updated_at = ?,
                completed_at = CASE WHEN ? THEN ? ELSE completed_at END,
                stop_reason = ?, lease_owner = NULL, lease_expires_at = NULL,
                last_heartbeat_at = NULL
            WHERE task_id = ? AND status = ?
            """,
            (
                next_status.value,
                now,
                int(terminal),
                now,
                reason,
                task_id,
                expected.value,
            ),
        )
        if cursor.rowcount != 1:
            raise TaskConflictError("task changed during transition")
        self._append_event(
            connection,
            task_id,
            f"task.{next_status.value}",
            {"reason": reason},
            now,
        )

    def _assert_owner(
        self,
        task: TaskRecord,
        worker_id: str,
        expected_version: int,
    ) -> None:
        worker = _identifier(worker_id, "worker_id")
        if task.version != expected_version:
            raise TaskLeaseError("task version changed")
        if task.lease_owner != worker:
            raise TaskLeaseError("worker does not own task lease")
        if task.lease_expires_at is not None and task.lease_expires_at <= self._clock():
            raise TaskLeaseError("task lease expired")

    def _append_event(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        timestamp: float,
    ) -> None:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
            "FROM background_task_events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO background_task_events(
                task_id, sequence, event_type, payload_json, timestamp
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                task_id,
                int(row["next_sequence"]),
                _required_text(event_type, "event_type")[:160],
                _json_dump(payload),
                timestamp,
            ),
        )

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS background_task_schema (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    version INTEGER NOT NULL
                );
                INSERT INTO background_task_schema(singleton, version)
                VALUES (1, 1) ON CONFLICT(singleton) DO NOTHING;

                CREATE TABLE IF NOT EXISTS background_tasks (
                    task_id TEXT PRIMARY KEY,
                    parent_run_id TEXT,
                    request_digest TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    attempt INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    max_steps INTEGER NOT NULL,
                    timeout_seconds REAL NOT NULL,
                    cancel_requested INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    last_heartbeat_at REAL,
                    side_effect_state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    stop_reason TEXT,
                    output_json TEXT,
                    error_json TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS background_task_dependencies (
                    task_id TEXT NOT NULL REFERENCES background_tasks(task_id),
                    depends_on TEXT NOT NULL REFERENCES background_tasks(task_id),
                    PRIMARY KEY(task_id, depends_on),
                    CHECK(task_id <> depends_on)
                );

                CREATE TABLE IF NOT EXISTS background_task_events (
                    task_id TEXT NOT NULL REFERENCES background_tasks(task_id),
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    PRIMARY KEY(task_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS background_task_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES background_tasks(task_id),
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS background_tasks_queue_idx
                ON background_tasks(status, created_at);
                CREATE INDEX IF NOT EXISTS background_tasks_parent_idx
                ON background_tasks(parent_run_id, created_at);
                CREATE INDEX IF NOT EXISTS background_task_events_lookup_idx
                ON background_task_events(task_id, sequence);
                CREATE INDEX IF NOT EXISTS background_task_dependencies_reverse_idx
                ON background_task_dependencies(depends_on, task_id);
                """
            )
            row = connection.execute(
                "SELECT version FROM background_task_schema WHERE singleton = 1"
            ).fetchone()
            if row is None or int(row["version"]) != self.SCHEMA_VERSION:
                raise TaskConflictError("unsupported background task schema version")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _get_task(connection: sqlite3.Connection, task_id: str) -> TaskRecord:
        row = connection.execute(
            "SELECT * FROM background_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"unknown task: {task_id}")
        return SQLiteDurableTaskStore._row_to_task(connection, row)

    @staticmethod
    def _row_to_task(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> TaskRecord:
        dependencies = tuple(
            value["depends_on"]
            for value in connection.execute(
                "SELECT depends_on FROM background_task_dependencies "
                "WHERE task_id = ? ORDER BY depends_on",
                (row["task_id"],),
            ).fetchall()
        )
        return TaskRecord(
            task_id=row["task_id"],
            parent_run_id=row["parent_run_id"],
            objective=row["objective"],
            workspace=row["workspace"],
            status=TaskStatus(row["status"]),
            version=int(row["version"]),
            attempt=int(row["attempt"]),
            max_attempts=int(row["max_attempts"]),
            max_steps=int(row["max_steps"]),
            timeout_seconds=float(row["timeout_seconds"]),
            cancel_requested=bool(row["cancel_requested"]),
            lease_owner=row["lease_owner"],
            lease_expires_at=(
                float(row["lease_expires_at"])
                if row["lease_expires_at"] is not None
                else None
            ),
            last_heartbeat_at=(
                float(row["last_heartbeat_at"])
                if row["last_heartbeat_at"] is not None
                else None
            ),
            side_effect_state=row["side_effect_state"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            started_at=(
                float(row["started_at"]) if row["started_at"] is not None else None
            ),
            completed_at=(
                float(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
            stop_reason=row["stop_reason"],
            output=(
                json.loads(row["output_json"])
                if row["output_json"] is not None
                else None
            ),
            error=(
                json.loads(row["error_json"])
                if row["error_json"] is not None
                else None
            ),
            metadata=json.loads(row["metadata_json"]),
            dependencies=dependencies,
        )


def _validate_spec(spec: TaskSpec) -> TaskSpec:
    task_id = _identifier(spec.task_id, "task_id")
    objective = _required_text(spec.objective, "objective")
    workspace = _required_text(spec.workspace, "workspace")
    parent_run_id = (
        _identifier(spec.parent_run_id, "parent_run_id")
        if spec.parent_run_id is not None
        else None
    )
    dependencies = tuple(dict.fromkeys(_identifier(value, "dependency") for value in spec.dependencies))
    if task_id in dependencies:
        raise ValueError("task cannot depend on itself")
    if isinstance(spec.max_steps, bool) or not 1 <= spec.max_steps <= 10_000:
        raise ValueError("max_steps must be within [1, 10000]")
    if spec.timeout_seconds <= 0 or spec.timeout_seconds > 86_400:
        raise ValueError("timeout_seconds must be within (0, 86400]")
    if isinstance(spec.max_attempts, bool) or not 1 <= spec.max_attempts <= 20:
        raise ValueError("max_attempts must be within [1, 20]")
    idempotency_key = (
        _identifier(spec.idempotency_key, "idempotency_key")
        if spec.idempotency_key
        else None
    )
    metadata = dict(spec.metadata)
    _json_dump(metadata)
    return TaskSpec(
        task_id=task_id,
        objective=objective,
        workspace=workspace,
        parent_run_id=parent_run_id,
        dependencies=dependencies,
        max_steps=spec.max_steps,
        timeout_seconds=float(spec.timeout_seconds),
        max_attempts=spec.max_attempts,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )


def _spec_digest(spec: TaskSpec) -> str:
    payload = asdict(spec)
    payload.pop("idempotency_key", None)
    return hashlib.sha256(_json_dump(payload).encode("utf-8")).hexdigest()


def _identifier(value: str, label: str) -> str:
    normalized = _required_text(value, label)
    if len(normalized) > 200:
        raise ValueError(f"{label} exceeds 200 characters")
    return normalized


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = ["SQLiteDurableTaskStore"]
