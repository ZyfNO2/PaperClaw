"""SQLite Repository for the v0.04 Context Runtime.

The Repository is the only component that touches the SQLite connection. It
serializes writes with a single-writer lock so model calls, Bash, and file
I/O never hold a database write transaction (SOP §5.4).

Transaction ordering for a Runtime state commit (SOP §5.3)::

    BEGIN IMMEDIATE
      1. append SessionEvent
      2. update materialized TaskState / Run state
      3. insert ContextItem / Snapshot (if produced this step)
      4. insert Checkpoint (only at safe step boundary)
    COMMIT

Idempotency rules:

- Duplicate ``event_id`` on ``session_events`` is rejected by the UNIQUE
  constraint. ``append_event`` returns ``False`` when a duplicate is detected;
  callers MUST treat this as idempotent success, not an error.
- ``sequence`` is allocated atomically inside the writer lock; no two events
  in the same Run can share a sequence.
- ``idempotency_ledger`` records ``operation_id`` for side-effecting tool
  calls so a replay can be detected.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Protocol

from paperclaw.context.contracts import (
    Checkpoint,
    ContextBudget,
    ContextItem,
    ContextSnapshot,
    SessionEvent,
    SCOPE_SHARED,
    utc_now_iso,
    validate_event,
    validate_item,
)
from paperclaw.context.migrations import (
    CURRENT_SCHEMA_VERSION,
    MigrationRunner,
    open_connection,
)


# ---------------------------------------------------------------------------
# Repository protocol
# ---------------------------------------------------------------------------


class Repository(Protocol):
    """Storage boundary for the Context Runtime.

    The protocol exists so tests can substitute in-memory fakes without going
    through SQLite. All persistence decisions (idempotency, sequence ordering,
    migration, backup) live behind this interface.
    """

    # -- schema ---------------------------------------------------------

    def current_schema_version(self) -> int: ...

    def migrate(self, make_backup: bool = True) -> int: ...

    # -- conversations / runs ------------------------------------------

    def create_conversation(self, conversation_id: str, metadata: dict[str, Any] | None = None) -> None: ...

    def start_run(
        self,
        run_id: str,
        conversation_id: str,
        agent_id: str,
        role: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def end_run(self, run_id: str, stop_reason: str | None = None) -> None: ...

    # -- session events -------------------------------------------------

    def next_sequence(self, run_id: str) -> int: ...

    def append_event(self, event: SessionEvent) -> bool: ...

    def list_events(self, run_id: str, since_sequence: int = 0) -> list[SessionEvent]: ...

    def last_committed_sequence(self, run_id: str) -> int: ...

    # -- messages -------------------------------------------------------

    def append_message(
        self,
        message_id: str,
        conversation_id: str,
        run_id: str,
        role: str,
        content: str,
        sequence: int,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]: ...

    # -- task state -----------------------------------------------------

    def upsert_task_state(
        self,
        task_id: str,
        run_id: str,
        status: str,
        payload: dict[str, Any],
        *,
        bump_revision: bool = True,
    ) -> int: ...

    def get_task_state(self, task_id: str) -> dict[str, Any] | None: ...

    def list_task_states(self, run_id: str) -> list[dict[str, Any]]: ...

    # -- context items --------------------------------------------------

    def insert_context_item(self, item: ContextItem) -> None: ...

    def insert_context_items(self, items: Iterable[ContextItem]) -> int: ...

    def get_context_item(self, item_id: str) -> ContextItem | None: ...

    def list_context_items(
        self,
        run_id: str,
        *,
        at_sequence: int | None = None,
        layer: str | None = None,
        task_id: str | None = None,
    ) -> list[ContextItem]: ...

    # -- context snapshots ---------------------------------------------

    def insert_snapshot(self, snapshot: ContextSnapshot) -> None: ...

    def list_snapshots(self, run_id: str) -> list[ContextSnapshot]: ...

    # -- checkpoints ----------------------------------------------------

    def insert_checkpoint(self, checkpoint: Checkpoint) -> None: ...

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None: ...

    # -- idempotency ----------------------------------------------------

    def record_idempotent_operation(
        self,
        operation_id: str,
        event_type: str,
        payload_hash: str,
        run_id: str | None = None,
    ) -> bool: ...

    # -- lifecycle ------------------------------------------------------

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# SQLite implementation
# ---------------------------------------------------------------------------


class SQLiteRepository:
    """SQLite-backed Repository. Single writer, multiple readers.

    Concurrency:

    - WAL is enabled by ``open_connection`` so readers do not block writers.
    - A single ``_write_lock`` serializes write transactions across threads.
      Long-running model calls, Bash, and file I/O MUST happen outside any
      write transaction; the lock is released as soon as COMMIT returns.
    - ``busy_timeout`` is set on the connection so transient lock contention
      waits instead of failing immediately.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        backup_dir: Path | None = None,
        wal: bool = True,
        busy_timeout_ms: int = 5000,
        migrate: bool = True,
    ):
        self._db_path = str(db_path)
        self._backup_dir = backup_dir
        self._conn = open_connection(db_path, wal=wal, busy_timeout_ms=busy_timeout_ms)
        self._write_lock = threading.RLock()
        self._closed = False
        if migrate:
            runner = MigrationRunner(self._conn, backup_dir=backup_dir)
            result = runner.migrate(make_backup=backup_dir is not None)
            if not result.ok:
                self._conn.close()
                raise RuntimeError(
                    f"schema migration failed: {result.error}"
                )

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def current_schema_version(self) -> int:
        return MigrationRunner(self._conn).current_version()

    def migrate(self, make_backup: bool = True) -> int:
        with self._write_lock:
            runner = MigrationRunner(self._conn, backup_dir=self._backup_dir)
            result = runner.migrate(make_backup=make_backup)
            if not result.ok:
                raise RuntimeError(f"migration failed: {result.error}")
            return result.applied_version

    # ------------------------------------------------------------------
    # conversations / runs
    # ------------------------------------------------------------------

    def create_conversation(self, conversation_id: str, metadata: dict[str, Any] | None = None) -> None:
        with self._write_lock:
            self._exec_txn(
                "INSERT OR IGNORE INTO conversations (conversation_id, created_at, metadata) "
                "VALUES (?, ?, ?)",
                (conversation_id, utc_now_iso(), json.dumps(metadata or {})),
            )

    def start_run(
        self,
        run_id: str,
        conversation_id: str,
        agent_id: str,
        role: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._write_lock:
            # Ensure conversation exists; ignore if already present.
            self._exec_txn(
                "INSERT OR IGNORE INTO conversations (conversation_id, created_at, metadata) "
                "VALUES (?, ?, ?)",
                (conversation_id, utc_now_iso(), json.dumps({})),
            )
            self._exec_txn(
                "INSERT INTO runs (run_id, conversation_id, agent_id, role, task_id, "
                "created_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    conversation_id,
                    agent_id,
                    role,
                    task_id,
                    utc_now_iso(),
                    json.dumps(metadata or {}),
                ),
            )

    def end_run(self, run_id: str, stop_reason: str | None = None) -> None:
        with self._write_lock:
            self._exec_txn(
                "UPDATE runs SET ended_at = ?, stop_reason = ? WHERE run_id = ?",
                (utc_now_iso(), stop_reason, run_id),
            )

    # ------------------------------------------------------------------
    # session events
    # ------------------------------------------------------------------

    def next_sequence(self, run_id: str) -> int:
        """Return the next sequence number for ``run_id``.

        Sequence allocation happens under the writer lock so concurrent
        appenders cannot race. Sequences start at 1; an empty Run returns 1.
        """
        with self._write_lock:
            cur = self._conn.execute(
                "SELECT MAX(sequence) FROM session_events WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
            current = int(row[0]) if row and row[0] is not None else 0
            return current + 1

    def append_event(self, event: SessionEvent) -> bool:
        """Append one SessionEvent.

        Returns:
            True if the event was appended.
            False if a duplicate ``event_id`` was already present (idempotent
            success — the caller should treat this as already-committed).

        Raises:
            ValueError: if event invariants are violated.
            sqlite3.IntegrityError: re-raised for ``run_id+sequence`` UNIQUE
                collisions, which indicate a real concurrency bug (two events
                with the same sequence in the same Run). The ``event_id``
                duplicate case is treated as idempotent success and returns
                False instead of raising.

        Note:
            ``next_sequence`` followed by ``append_event`` is NOT atomic
            across threads. Concurrent callers MUST use
            :meth:`append_event_with_auto_sequence` to atomically allocate
            the next sequence and append the event under the writer lock.
        """
        validate_event(event)
        with self._write_lock:
            # Check event_id existence first so we can distinguish idempotent
            # success (same event_id seen before) from a real concurrency bug
            # (different event_id but same run_id+sequence). The (run_id,
            # sequence) UNIQUE constraint would otherwise fire first and we
            # would have to inspect the error message — fragile.
            existing = self._conn.execute(
                "SELECT 1 FROM session_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                return False
            try:
                self._exec_txn(
                    "INSERT INTO session_events (event_id, conversation_id, run_id, "
                    "sequence, event_type, payload, created_at, schema_version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.conversation_id,
                        event.run_id,
                        event.sequence,
                        event.event_type,
                        json.dumps(event.payload),
                        event.created_at,
                        int(event.payload.get("schema_version", 1)),
                    ),
                )
            except sqlite3.IntegrityError:
                # At this point event_id was confirmed unique above, so the
                # only remaining UNIQUE constraint is (run_id, sequence).
                raise
            return True

    def append_event_with_auto_sequence(
        self,
        *,
        event_id: str,
        conversation_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str | None = None,
    ) -> tuple[bool, int]:
        """Atomically allocate the next sequence and append the event.

        This is the concurrency-safe variant of ``next_sequence`` + ``append_event``.
        The sequence allocation and the INSERT happen under the same writer
        lock, so concurrent callers cannot race on the same sequence.

        Returns ``(appended, sequence)``:

        - ``(True, sequence)``: the event was newly appended; ``sequence`` is
          the allocated monotonic sequence number.
        - ``(False, existing_sequence)``: a duplicate ``event_id`` was already
          present (idempotent success); ``existing_sequence`` is the sequence
          of the original event so callers can confirm the prior write.
        """
        if "schema_version" not in payload:
            raise ValueError("payload must carry schema_version")
        if not event_type:
            raise ValueError("event_type must be non-empty")
        timestamp = created_at or utc_now_iso()
        with self._write_lock:
            existing = self._conn.execute(
                "SELECT sequence FROM session_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing is not None:
                return (False, int(existing["sequence"]))
            cur = self._conn.execute(
                "SELECT MAX(sequence) FROM session_events WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
            current = int(row[0]) if row and row[0] is not None else 0
            sequence = current + 1
            try:
                self._exec_txn(
                    "INSERT INTO session_events (event_id, conversation_id, run_id, "
                    "sequence, event_type, payload, created_at, schema_version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        conversation_id,
                        run_id,
                        sequence,
                        event_type,
                        json.dumps(payload),
                        timestamp,
                        int(payload.get("schema_version", 1)),
                    ),
                )
            except sqlite3.IntegrityError:
                # Should not happen: we just allocated the sequence under the
                # writer lock. If it does, surface it as a real bug.
                raise
            return (True, sequence)

    def list_events(self, run_id: str, since_sequence: int = 0) -> list[SessionEvent]:
        cur = self._conn.execute(
            "SELECT event_id, conversation_id, run_id, sequence, event_type, payload, "
            "created_at FROM session_events WHERE run_id = ? AND sequence > ? "
            "ORDER BY sequence ASC",
            (run_id, since_sequence),
        )
        events: list[SessionEvent] = []
        for row in cur.fetchall():
            events.append(
                SessionEvent(
                    event_id=row["event_id"],
                    conversation_id=row["conversation_id"],
                    run_id=row["run_id"],
                    sequence=int(row["sequence"]),
                    event_type=row["event_type"],
                    payload=json.loads(row["payload"]),
                    created_at=row["created_at"],
                )
            )
        return events

    def last_committed_sequence(self, run_id: str) -> int:
        cur = self._conn.execute(
            "SELECT MAX(sequence) FROM session_events WHERE run_id = ?",
            (run_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------

    def append_message(
        self,
        message_id: str,
        conversation_id: str,
        run_id: str,
        role: str,
        content: str,
        sequence: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._write_lock:
            self._exec_txn(
                "INSERT INTO messages (message_id, conversation_id, run_id, role, "
                "content, sequence, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    conversation_id,
                    run_id,
                    role,
                    content,
                    sequence,
                    utc_now_iso(),
                    json.dumps(metadata or {}),
                ),
            )

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT message_id, conversation_id, run_id, role, content, sequence, "
            "created_at, metadata FROM messages WHERE conversation_id = ? "
            "ORDER BY sequence ASC",
            (conversation_id,),
        )
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            out.append(
                {
                    "message_id": row["message_id"],
                    "conversation_id": row["conversation_id"],
                    "run_id": row["run_id"],
                    "role": row["role"],
                    "content": row["content"],
                    "sequence": int(row["sequence"]),
                    "created_at": row["created_at"],
                    "metadata": json.loads(row["metadata"]),
                }
            )
        return out

    # ------------------------------------------------------------------
    # task state
    # ------------------------------------------------------------------

    def upsert_task_state(
        self,
        task_id: str,
        run_id: str,
        status: str,
        payload: dict[str, Any],
        *,
        bump_revision: bool = True,
    ) -> int:
        """Upsert a TaskState row and return the new revision.

        Revisions are monotonic. ``bump_revision=False`` is used when replaying
        an existing event log into a fresh materialized view.
        """
        with self._write_lock:
            existing = self._conn.execute(
                "SELECT revision FROM task_states WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if existing is None:
                revision = 0
                self._exec_txn(
                    "INSERT INTO task_states (task_id, run_id, status, revision, "
                    "payload, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (task_id, run_id, status, revision, json.dumps(payload), utc_now_iso()),
                )
            else:
                revision = int(existing["revision"]) + (1 if bump_revision else 0)
                self._exec_txn(
                    "UPDATE task_states SET run_id = ?, status = ?, revision = ?, "
                    "payload = ?, updated_at = ? WHERE task_id = ?",
                    (run_id, status, revision, json.dumps(payload), utc_now_iso(), task_id),
                )
            return revision

    def get_task_state(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT task_id, run_id, status, revision, payload, updated_at "
            "FROM task_states WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "run_id": row["run_id"],
            "status": row["status"],
            "revision": int(row["revision"]),
            "payload": json.loads(row["payload"]),
            "updated_at": row["updated_at"],
        }

    def list_task_states(self, run_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT task_id, run_id, status, revision, payload, updated_at "
            "FROM task_states WHERE run_id = ? ORDER BY revision ASC",
            (run_id,),
        )
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            out.append(
                {
                    "task_id": row["task_id"],
                    "run_id": row["run_id"],
                    "status": row["status"],
                    "revision": int(row["revision"]),
                    "payload": json.loads(row["payload"]),
                    "updated_at": row["updated_at"],
                }
            )
        return out

    # ------------------------------------------------------------------
    # context items
    # ------------------------------------------------------------------

    def insert_context_item(self, item: ContextItem) -> None:
        validate_item(item)
        with self._write_lock:
            self._exec_txn(
                "INSERT INTO context_items (item_id, run_id, task_id, layer, kind, "
                "content, source_type, source_ref, trust_level, source_created_sequence, "
                "priority, scope, valid_from_sequence, valid_to_sequence, "
                "supersedes_item_id, estimated_tokens, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._item_to_row(item),
            )

    def insert_context_items(self, items: Iterable[ContextItem]) -> int:
        items_list = list(items)
        for item in items_list:
            validate_item(item)
        with self._write_lock:
            self._exec_txn_many(
                "INSERT INTO context_items (item_id, run_id, task_id, layer, kind, "
                "content, source_type, source_ref, trust_level, source_created_sequence, "
                "priority, scope, valid_from_sequence, valid_to_sequence, "
                "supersedes_item_id, estimated_tokens, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [self._item_to_row(item) for item in items_list],
            )
            return len(items_list)

    def get_context_item(self, item_id: str) -> ContextItem | None:
        row = self._conn.execute(
            "SELECT * FROM context_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def list_context_items(
        self,
        run_id: str,
        *,
        at_sequence: int | None = None,
        layer: str | None = None,
        task_id: str | None = None,
    ) -> list[ContextItem]:
        """List context items for a Run.

        ``at_sequence`` filters to items effective at that sequence
        (``valid_from_sequence <= at_sequence`` and either
        ``valid_to_sequence IS NULL`` or ``> at_sequence``).
        """
        query = "SELECT * FROM context_items WHERE run_id = ?"
        params: list[Any] = [run_id]
        if at_sequence is not None:
            query += " AND valid_from_sequence <= ? AND (valid_to_sequence IS NULL OR valid_to_sequence > ?)"
            params.extend([at_sequence, at_sequence])
        if layer is not None:
            query += " AND layer = ?"
            params.append(layer)
        if task_id is not None:
            query += " AND (task_id = ? OR task_id IS NULL)"
            params.append(task_id)
        query += " ORDER BY valid_from_sequence ASC, priority DESC"
        cur = self._conn.execute(query, params)
        return [self._row_to_item(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # context snapshots
    # ------------------------------------------------------------------

    def insert_snapshot(self, snapshot: ContextSnapshot) -> None:
        with self._write_lock:
            self._exec_txn(
                "INSERT INTO context_snapshots (snapshot_id, run_id, agent_id, role, "
                "task_id, source_item_ids, excluded_items, rendered_hash, "
                "estimated_tokens, estimator, created_sequence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.snapshot_id,
                    snapshot.run_id,
                    snapshot.agent_id,
                    snapshot.role,
                    snapshot.task_id,
                    json.dumps(list(snapshot.source_item_ids)),
                    json.dumps(list(snapshot.excluded_items)),
                    snapshot.rendered_hash,
                    int(snapshot.estimated_tokens),
                    snapshot.estimator,
                    int(snapshot.created_sequence),
                    utc_now_iso(),
                ),
            )

    def list_snapshots(self, run_id: str) -> list[ContextSnapshot]:
        cur = self._conn.execute(
            "SELECT * FROM context_snapshots WHERE run_id = ? ORDER BY created_sequence ASC",
            (run_id,),
        )
        out: list[ContextSnapshot] = []
        for row in cur.fetchall():
            out.append(
                ContextSnapshot(
                    snapshot_id=row["snapshot_id"],
                    run_id=row["run_id"],
                    agent_id=row["agent_id"],
                    role=row["role"],
                    task_id=row["task_id"],
                    source_item_ids=tuple(json.loads(row["source_item_ids"])),
                    excluded_items=tuple(json.loads(row["excluded_items"])),
                    rendered_hash=row["rendered_hash"],
                    estimated_tokens=int(row["estimated_tokens"]),
                    estimator=row["estimator"],
                    created_sequence=int(row["created_sequence"]),
                )
            )
        return out

    # ------------------------------------------------------------------
    # checkpoints
    # ------------------------------------------------------------------

    def insert_checkpoint(self, checkpoint: Checkpoint) -> None:
        with self._write_lock:
            self._exec_txn(
                "INSERT INTO checkpoints (checkpoint_id, run_id, last_committed_sequence, "
                "task_state_revision, budget_state, pending_operations, file_snapshots, "
                "state_hash, schema_version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    checkpoint.checkpoint_id,
                    checkpoint.run_id,
                    int(checkpoint.last_committed_sequence),
                    int(checkpoint.task_state_revision),
                    json.dumps(checkpoint.budget_state),
                    json.dumps(list(checkpoint.pending_operations)),
                    json.dumps(list(checkpoint.file_snapshots)),
                    checkpoint.state_hash,
                    int(checkpoint.schema_version),
                    checkpoint.created_at,
                ),
            )

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE run_id = ? "
            "ORDER BY last_committed_sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            checkpoint_id=row["checkpoint_id"],
            run_id=row["run_id"],
            last_committed_sequence=int(row["last_committed_sequence"]),
            task_state_revision=int(row["task_state_revision"]),
            budget_state=json.loads(row["budget_state"]),
            pending_operations=tuple(json.loads(row["pending_operations"])),
            file_snapshots=tuple(json.loads(row["file_snapshots"])),
            state_hash=row["state_hash"],
            schema_version=int(row["schema_version"]),
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    # idempotency ledger
    # ------------------------------------------------------------------

    def record_idempotent_operation(
        self,
        operation_id: str,
        event_type: str,
        payload_hash: str,
        run_id: str | None = None,
    ) -> bool:
        """Record a side-effecting operation idempotently.

        Returns True if this is the first time the operation was seen
        (caller should proceed), False if it has been recorded before
        (caller should treat as already-committed and skip side effects).
        """
        with self._write_lock:
            existing = self._conn.execute(
                "SELECT first_seen_at, seen_count FROM idempotency_ledger WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            now = utc_now_iso()
            if existing is None:
                self._exec_txn(
                    "INSERT INTO idempotency_ledger (operation_id, run_id, event_type, "
                    "payload_hash, first_seen_at, last_seen_at, seen_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (operation_id, run_id, event_type, payload_hash, now, now),
                )
                return True
            seen_count = int(existing["seen_count"]) + 1
            self._exec_txn(
                "UPDATE idempotency_ledger SET last_seen_at = ?, seen_count = ? WHERE operation_id = ?",
                (now, seen_count, operation_id),
            )
            return False

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._write_lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _exec_txn(self, sql: str, params: tuple[Any, ...]) -> None:
        """Execute one statement inside a fresh BEGIN IMMEDIATE transaction."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(sql, params)
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    def _exec_txn_many(self, sql: str, param_batches: list[tuple[Any, ...]]) -> None:
        """Execute the same statement with multiple parameter sets in one txn."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.executemany(sql, param_batches)
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    @staticmethod
    def _item_to_row(item: ContextItem) -> tuple[Any, ...]:
        return (
            item.item_id,
            item.run_id,
            item.task_id,
            item.layer,
            item.kind,
            item.content,
            item.source.source_type,
            item.source.source_ref,
            item.source.trust_level,
            int(item.source.created_sequence),
            int(item.priority),
            json.dumps(list(item.scope)),
            int(item.valid_from_sequence),
            int(item.valid_to_sequence) if item.valid_to_sequence is not None else None,
            item.supersedes_item_id,
            int(item.estimated_tokens),
            json.dumps(item.metadata),
            utc_now_iso(),
        )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ContextItem:
        from paperclaw.context.contracts import ContextSource

        return ContextItem(
            item_id=row["item_id"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            layer=row["layer"],
            kind=row["kind"],
            content=row["content"],
            source=ContextSource(
                source_type=row["source_type"],
                source_ref=row["source_ref"],
                trust_level=row["trust_level"],
                created_sequence=int(row["source_created_sequence"]),
            ),
            priority=int(row["priority"]),
            scope=tuple(json.loads(row["scope"])),
            valid_from_sequence=int(row["valid_from_sequence"]),
            valid_to_sequence=int(row["valid_to_sequence"])
            if row["valid_to_sequence"] is not None
            else None,
            supersedes_item_id=row["supersedes_item_id"],
            estimated_tokens=int(row["estimated_tokens"]),
            metadata=json.loads(row["metadata"]),
        )


# ---------------------------------------------------------------------------
# Composite commit (SOP §5.3)
# ---------------------------------------------------------------------------


def commit_runtime_step(
    repo: Repository,
    *,
    run_id: str,
    conversation_id: str,
    event: SessionEvent,
    task_state_updates: Iterable[tuple[str, str, dict[str, Any]]] | None = None,
    context_items: Iterable[ContextItem] | None = None,
    snapshot: ContextSnapshot | None = None,
    checkpoint: Checkpoint | None = None,
) -> bool:
    """Apply a single Runtime state commit in SOP §5.3 ordering.

    The Repository interface exposes granular methods so callers can compose
    transactions. This helper enforces the canonical order:

    1. Append SessionEvent.
    2. Update materialized TaskState rows.
    3. Insert ContextItems / Snapshot (if produced this step).
    4. Insert Checkpoint (only at safe step boundary).

    Returns ``True`` if the event was newly committed, ``False`` if a
    duplicate ``event_id`` was detected (idempotent success).
    """
    appended = repo.append_event(event)
    if not appended:
        return False

    if task_state_updates:
        for task_id, status, payload in task_state_updates:
            repo.upsert_task_state(task_id, run_id, status, payload)

    if context_items:
        # SQLiteRepository.insert_context_items takes any iterable
        repo.insert_context_items(context_items)

    if snapshot is not None:
        repo.insert_snapshot(snapshot)

    if checkpoint is not None:
        repo.insert_checkpoint(checkpoint)

    return True
