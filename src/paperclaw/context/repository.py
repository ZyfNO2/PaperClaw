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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol, TYPE_CHECKING

from paperclaw.context.contracts import (
    Checkpoint,
    ContextItem,
    ContextSnapshot,
    SessionEvent,
    utc_now_iso,
    validate_event,
    validate_item,
)
from paperclaw.context.migrations import MigrationRunner, open_connection

if TYPE_CHECKING:
    from paperclaw.memory.contracts import MemoryItem, MemorySnapshot


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

    def append_event_with_auto_sequence(
        self,
        *,
        event_id: str,
        conversation_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str | None = None,
        turn_id: str | None = None,
        idempotency_key: str | None = None,
        payload_ref: str | None = None,
    ) -> tuple[bool, int]: ...

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

    def append_message_with_auto_sequence(
        self,
        *,
        message_id: str,
        conversation_id: str,
        run_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, int]: ...

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

    def get_snapshot(self, snapshot_id: str) -> ContextSnapshot | None: ...

    # -- structured persistent memory ---------------------------------

    def insert_memory_item(self, item: "MemoryItem") -> None: ...

    def get_memory_item(self, memory_id: str) -> "MemoryItem | None": ...

    def list_active_memory(self, scope_type: str, scope_id: str) -> list["MemoryItem"]: ...

    def list_all_memory(self, scope_type: str, scope_id: str) -> list["MemoryItem"]: ...

    def list_memory_history(self, memory_id: str) -> list["MemoryItem"]: ...

    def search_memory_items(
        self,
        query: str,
        scope_type: str,
        scope_id: str,
        limit: int = 10,
    ) -> list["MemoryItem"]: ...

    def insert_memory_snapshot(self, snapshot: "MemorySnapshot") -> None: ...

    def get_memory_snapshot(self, conversation_id: str) -> "MemorySnapshot | None": ...

    def insert_memory_conflict_decision(self, decision: Any) -> None: ...

    def list_memory_conflict_decisions(
        self, candidate_memory_id: str | None = None
    ) -> list[Any]: ...

    # -- run inspection / reconstruction --------------------------------

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...

    def latest_run_for_conversation(self, conversation_id: str) -> dict[str, Any] | None: ...

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

    # -- composite commit (SOP §5.3) -----------------------------------

    def commit_runtime_step(
        self,
        *,
        run_id: str,
        conversation_id: str,
        event: SessionEvent,
        task_state_updates: Iterable[tuple[str, str, dict[str, Any]]] | None = None,
        context_items: Iterable[ContextItem] | None = None,
        snapshot: ContextSnapshot | None = None,
        checkpoint: Checkpoint | None = None,
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
                # LOW-2 fix: mark closed so a later close() is a no-op rather
                # than raising "cannot operate on a closed connection".
                self._closed = True
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

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT run_id, conversation_id, agent_id, role, task_id, created_at, "
            "ended_at, stop_reason, metadata FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "conversation_id": row["conversation_id"],
            "agent_id": row["agent_id"],
            "role": row["role"],
            "task_id": row["task_id"],
            "created_at": row["created_at"],
            "ended_at": row["ended_at"],
            "stop_reason": row["stop_reason"],
            "metadata": json.loads(row["metadata"] or "{}"),
        }

    def latest_run_for_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT run_id FROM runs WHERE conversation_id = ? "
            "ORDER BY created_at DESC, run_id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return self.get_run(str(row["run_id"])) if row is not None else None

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
                "SELECT 1 FROM session_events WHERE event_id = ? "
                "OR (run_id = ? AND idempotency_key = ? AND idempotency_key IS NOT NULL)",
                (event.event_id, event.run_id, event.idempotency_key),
            ).fetchone()
            if existing is not None:
                return False
            try:
                self._exec_txn(
                    "INSERT INTO session_events (event_id, conversation_id, run_id, "
                    "sequence, event_type, payload, created_at, schema_version, "
                    "turn_id, idempotency_key, payload_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.conversation_id,
                        event.run_id,
                        event.sequence,
                        event.event_type,
                        json.dumps(event.payload),
                        event.created_at,
                        int(event.schema_version),
                        event.turn_id,
                        event.idempotency_key,
                        event.payload_ref,
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
        turn_id: str | None = None,
        idempotency_key: str | None = None,
        payload_ref: str | None = None,
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
        timestamp = created_at or utc_now_iso()
        schema_version = int(payload.get("schema_version", 0))
        validate_event(
            SessionEvent(
                event_id=event_id,
                conversation_id=conversation_id,
                run_id=run_id,
                sequence=0,
                event_type=event_type,
                payload=payload,
                created_at=timestamp,
                turn_id=turn_id,
                idempotency_key=idempotency_key,
                payload_ref=payload_ref,
                schema_version=schema_version,
            )
        )
        with self._write_lock:
            try:
                # The sequence read must be inside BEGIN IMMEDIATE. A
                # repository-local lock protects threads sharing one
                # connection; the SQLite write transaction also protects
                # independent processes sharing the same database.
                self._conn.execute("BEGIN IMMEDIATE")
                existing = self._conn.execute(
                    "SELECT sequence FROM session_events WHERE event_id = ? "
                    "OR (run_id = ? AND idempotency_key = ? AND idempotency_key IS NOT NULL)",
                    (event_id, run_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    self._conn.execute("COMMIT")
                    return (False, int(existing["sequence"]))
                cur = self._conn.execute(
                    "SELECT MAX(sequence) FROM session_events WHERE run_id = ?",
                    (run_id,),
                )
                row = cur.fetchone()
                sequence = int(row[0]) + 1 if row and row[0] is not None else 1
                self._conn.execute(
                    "INSERT INTO session_events (event_id, conversation_id, run_id, "
                    "sequence, event_type, payload, created_at, schema_version, "
                    "turn_id, idempotency_key, payload_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        conversation_id,
                        run_id,
                        sequence,
                        event_type,
                        json.dumps(payload),
                        timestamp,
                        schema_version,
                        turn_id,
                        idempotency_key,
                        payload_ref,
                    ),
                )
                self._conn.execute("COMMIT")
                return (True, sequence)
            except sqlite3.IntegrityError:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                existing = self._conn.execute(
                    "SELECT sequence FROM session_events WHERE event_id = ? "
                    "OR (run_id = ? AND idempotency_key = ? AND idempotency_key IS NOT NULL)",
                    (event_id, run_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    return (False, int(existing["sequence"]))
                raise
            except sqlite3.Error:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    def list_events(self, run_id: str, since_sequence: int = 0) -> list[SessionEvent]:
        cur = self._conn.execute(
            "SELECT event_id, conversation_id, run_id, sequence, event_type, payload, "
            "created_at, schema_version, turn_id, idempotency_key, payload_ref "
            "FROM session_events WHERE run_id = ? AND sequence > ? "
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
                    turn_id=row["turn_id"],
                    idempotency_key=row["idempotency_key"],
                    payload_ref=row["payload_ref"],
                    schema_version=int(row["schema_version"]),
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
        """Append with caller-supplied sequence. NOT concurrency-safe.

        Callers that race on the same sequence will hit the v2 UNIQUE
        constraint and one INSERT will fail. Use
        :meth:`append_message_with_auto_sequence` instead — it allocates
        the sequence under the writer lock so concurrent callers cannot
        collide.
        """
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

    def append_message_with_auto_sequence(
        self,
        *,
        message_id: str,
        conversation_id: str,
        run_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """Atomically allocate the next message sequence and append.

        Sequence allocation and INSERT happen under the writer lock so
        concurrent ``SessionService.append_message`` callers cannot race
        on the same sequence number. Messages have their own sequence
        space, distinct from SessionEvent sequences.

        Returns ``(message_id, sequence)``.
        """
        with self._write_lock:
            cur = self._conn.execute(
                "SELECT MAX(sequence) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            row = cur.fetchone()
            current = int(row[0]) if row and row[0] is not None else 0
            sequence = current + 1
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
            return (message_id, sequence)

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
            return self._upsert_task_state_locked(
                task_id, run_id, status, payload, bump_revision=bump_revision
            )

    def _upsert_task_state_locked(
        self,
        task_id: str,
        run_id: str,
        status: str,
        payload: dict[str, Any],
        *,
        bump_revision: bool = True,
    ) -> int:
        """Same as ``upsert_task_state`` but assumes the caller already holds
        ``_write_lock`` and is inside an existing transaction (e.g. when called
        from ``commit_runtime_step``). Does NOT open its own BEGIN/COMMIT.

        The INSERT/UPDATE here use the connection's current transaction state;
        if no transaction is active, sqlite3 will autocommit per statement,
        which is incorrect for composite commits. Callers must ensure they are
        inside a ``BEGIN IMMEDIATE`` block.
        """
        existing = self._conn.execute(
            "SELECT revision FROM task_states WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        now = utc_now_iso()
        if existing is None:
            revision = 0
            self._conn.execute(
                "INSERT INTO task_states (task_id, run_id, status, revision, "
                "payload, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, run_id, status, revision, json.dumps(payload), now),
            )
        else:
            revision = int(existing["revision"]) + (1 if bump_revision else 0)
            self._conn.execute(
                "UPDATE task_states SET run_id = ?, status = ?, revision = ?, "
                "payload = ?, updated_at = ? WHERE task_id = ?",
                (run_id, status, revision, json.dumps(payload), now, task_id),
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
                "estimated_tokens, estimator, created_sequence, created_at, session_id, "
                "model_call_id, system_prompt_hash, static_prefix_hash, "
                "selected_memory_ids, selected_artifact_locators, selected_event_ids, "
                "event_range, compaction_summary_ref, omitted_counts, input_tokens, "
                "policy_fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    snapshot.session_id,
                    snapshot.model_call_id,
                    snapshot.system_prompt_hash,
                    snapshot.static_prefix_hash,
                    json.dumps(list(snapshot.selected_memory_ids)),
                    json.dumps(list(snapshot.selected_artifact_locators)),
                    json.dumps(list(snapshot.selected_event_ids)),
                    json.dumps(snapshot.event_range, sort_keys=True),
                    snapshot.compaction_summary_ref,
                    json.dumps(snapshot.omitted_counts, sort_keys=True),
                    snapshot.input_tokens,
                    snapshot.policy_fingerprint,
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
                    session_id=row["session_id"],
                    model_call_id=row["model_call_id"],
                    system_prompt_hash=row["system_prompt_hash"],
                    static_prefix_hash=row["static_prefix_hash"],
                    selected_memory_ids=tuple(json.loads(row["selected_memory_ids"] or "[]")),
                    selected_artifact_locators=tuple(
                        json.loads(row["selected_artifact_locators"] or "[]")
                    ),
                    selected_event_ids=tuple(json.loads(row["selected_event_ids"] or "[]")),
                    event_range=json.loads(row["event_range"] or "{}"),
                    compaction_summary_ref=row["compaction_summary_ref"],
                    omitted_counts=json.loads(row["omitted_counts"] or "{}"),
                    input_tokens=(
                        int(row["input_tokens"])
                        if row["input_tokens"] is not None
                        else None
                    ),
                    policy_fingerprint=row["policy_fingerprint"] or "",
                )
            )
        return out

    def get_snapshot(self, snapshot_id: str) -> ContextSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM context_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_context_snapshot(row)

    @staticmethod
    def _row_to_context_snapshot(row: sqlite3.Row) -> ContextSnapshot:
        return ContextSnapshot(
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
            session_id=row["session_id"],
            model_call_id=row["model_call_id"],
            system_prompt_hash=row["system_prompt_hash"],
            static_prefix_hash=row["static_prefix_hash"],
            selected_memory_ids=tuple(json.loads(row["selected_memory_ids"] or "[]")),
            selected_artifact_locators=tuple(
                json.loads(row["selected_artifact_locators"] or "[]")
            ),
            selected_event_ids=tuple(json.loads(row["selected_event_ids"] or "[]")),
            event_range=json.loads(row["event_range"] or "{}"),
            compaction_summary_ref=row["compaction_summary_ref"],
            omitted_counts=json.loads(row["omitted_counts"] or "{}"),
            input_tokens=(
                int(row["input_tokens"]) if row["input_tokens"] is not None else None
            ),
            policy_fingerprint=row["policy_fingerprint"] or "",
        )

    # ------------------------------------------------------------------
    # structured persistent memory
    # ------------------------------------------------------------------

    def insert_memory_item(self, item: "MemoryItem") -> None:
        """Append one immutable MemoryItem; never UPDATE an existing row."""
        from paperclaw.memory.contracts import MemoryItem

        if not isinstance(item, MemoryItem):
            raise TypeError("item must be a structured MemoryItem")
        with self._write_lock:
            self._exec_txn(
                "INSERT INTO memory_items (memory_id, scope_type, scope_id, kind, "
                "content, source_refs, trust_level, importance, pinned, "
                "created_from_run_id, created_from_sequence, supersedes_memory_id, "
                "tombstone, content_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._memory_item_to_row(item),
            )

    def get_memory_item(self, memory_id: str) -> "MemoryItem | None":
        row = self._conn.execute(
            "SELECT * FROM memory_items WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        return self._row_to_memory_item(row) if row is not None else None

    def list_active_memory(self, scope_type: str, scope_id: str) -> list["MemoryItem"]:
        """Return the deterministic non-tombstone head projection."""
        rows = self._conn.execute(
            "SELECT m.* FROM memory_items AS m "
            "WHERE m.scope_type = ? AND m.scope_id = ? AND m.tombstone = 0 "
            "AND NOT EXISTS ("
            "SELECT 1 FROM memory_items AS newer "
            "WHERE newer.supersedes_memory_id = m.memory_id "
            "AND newer.scope_type = m.scope_type AND newer.scope_id = m.scope_id"
            ") "
            "ORDER BY m.importance DESC, m.kind ASC, m.created_at ASC, m.memory_id ASC",
            (scope_type, scope_id),
        ).fetchall()
        return [self._row_to_memory_item(row) for row in rows]

    def list_all_memory(self, scope_type: str, scope_id: str) -> list["MemoryItem"]:
        rows = self._conn.execute(
            "SELECT * FROM memory_items WHERE scope_type = ? AND scope_id = ? "
            "ORDER BY created_at ASC, memory_id ASC",
            (scope_type, scope_id),
        ).fetchall()
        return [self._row_to_memory_item(row) for row in rows]

    def list_memory_history(self, memory_id: str) -> list["MemoryItem"]:
        """Return one immutable replacement/tombstone lineage in order."""
        first = self.get_memory_item(memory_id)
        if first is None:
            return []
        rows: dict[str, Any] = {first.memory_id: first}
        pending = [first.memory_id]
        while pending:
            current = pending.pop()
            children = self._conn.execute(
                "SELECT * FROM memory_items WHERE supersedes_memory_id = ? "
                "AND scope_type = ? AND scope_id = ?",
                (current, first.scope_type, first.scope_id),
            ).fetchall()
            for row in children:
                item = self._row_to_memory_item(row)
                if item.memory_id not in rows:
                    rows[item.memory_id] = item
                    pending.append(item.memory_id)
            parent = rows[current].supersedes_memory_id
            if parent and parent not in rows:
                parent_row = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id = ?",
                    (parent,),
                ).fetchone()
                if parent_row is not None:
                    parent_item = self._row_to_memory_item(parent_row)
                    rows[parent_item.memory_id] = parent_item
                    pending.append(parent_item.memory_id)
        return sorted(rows.values(), key=lambda item: (item.created_at, item.memory_id))

    def search_memory_items(
        self,
        query: str,
        scope_type: str,
        scope_id: str,
        limit: int = 10,
    ) -> list["MemoryItem"]:
        """Run deterministic local lexical recall over active Memory heads.

        The repository intentionally keeps a Python lexical fallback instead
        of requiring SQLite FTS5, which is not consistently compiled into all
        supported Windows Python distributions.
        """
        import re

        if limit < 1:
            return []
        tokens = tuple(re.findall(r"[\w]+", query.casefold()))
        candidates = self.list_active_memory(scope_type, scope_id)
        if not tokens:
            return candidates[:limit]
        ranked: list[tuple[int, "MemoryItem"]] = []
        for item in candidates:
            haystack = item.content.casefold()
            score = sum(haystack.count(token) for token in tokens)
            if score:
                ranked.append((score, item))
        ranked.sort(
            key=lambda pair: (
                -pair[0],
                -pair[1].importance,
                pair[1].kind,
                pair[1].created_at,
                pair[1].memory_id,
            )
        )
        return [item for _, item in ranked[:limit]]

    def insert_memory_snapshot(self, snapshot: "MemorySnapshot") -> None:
        from paperclaw.memory.contracts import MemorySnapshot

        if not isinstance(snapshot, MemorySnapshot):
            raise TypeError("snapshot must be a structured MemorySnapshot")
        with self._write_lock:
            self._exec_txn(
                "INSERT INTO memory_snapshots (snapshot_id, conversation_id, "
                "user_scope_id, project_scope_id, memory_ids, rendered_content, "
                "rendered_hash, estimated_tokens, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.snapshot_id,
                    snapshot.conversation_id,
                    snapshot.user_scope_id,
                    snapshot.project_scope_id,
                    json.dumps(list(snapshot.memory_ids), ensure_ascii=False),
                    snapshot.rendered_content,
                    snapshot.rendered_hash,
                    int(snapshot.estimated_tokens),
                    snapshot.created_at,
                ),
            )

    def get_memory_snapshot(self, conversation_id: str) -> "MemorySnapshot | None":
        row = self._conn.execute(
            "SELECT * FROM memory_snapshots WHERE conversation_id = ? "
            "ORDER BY created_at DESC, snapshot_id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        from paperclaw.memory.contracts import MemorySnapshot

        return MemorySnapshot(
            snapshot_id=row["snapshot_id"],
            conversation_id=row["conversation_id"],
            user_scope_id=row["user_scope_id"],
            project_scope_id=row["project_scope_id"],
            memory_ids=tuple(json.loads(row["memory_ids"])),
            rendered_content=row["rendered_content"],
            rendered_hash=row["rendered_hash"],
            estimated_tokens=int(row["estimated_tokens"]),
            created_at=row["created_at"],
        )

    def insert_memory_conflict_decision(self, decision: Any) -> None:
        from paperclaw.memory.contracts import MemoryConflictDecisionRecord

        if not isinstance(decision, MemoryConflictDecisionRecord):
            raise TypeError("decision must be a MemoryConflictDecisionRecord")
        with self._write_lock:
            self._exec_txn(
                "INSERT INTO memory_conflict_decisions (decision_id, candidate_memory_id, "
                "conflicting_memory_ids, decision, source_refs, created_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    decision.decision_id,
                    decision.candidate_memory_id,
                    json.dumps(list(decision.conflicting_memory_ids)),
                    decision.decision,
                    json.dumps(list(decision.source_refs)),
                    decision.created_at,
                    json.dumps(decision.metadata, sort_keys=True),
                ),
            )

    def list_memory_conflict_decisions(
        self, candidate_memory_id: str | None = None
    ) -> list[Any]:
        from paperclaw.memory.contracts import MemoryConflictDecisionRecord

        query = "SELECT * FROM memory_conflict_decisions"
        params: tuple[Any, ...] = ()
        if candidate_memory_id is not None:
            query += " WHERE candidate_memory_id = ?"
            params = (candidate_memory_id,)
        query += " ORDER BY created_at ASC, decision_id ASC"
        rows = self._conn.execute(query, params).fetchall()
        return [
            MemoryConflictDecisionRecord(
                decision_id=row["decision_id"],
                candidate_memory_id=row["candidate_memory_id"],
                conflicting_memory_ids=tuple(
                    json.loads(row["conflicting_memory_ids"])
                ),
                decision=row["decision"],
                source_refs=tuple(json.loads(row["source_refs"])),
                created_at=row["created_at"],
                metadata=json.loads(row["metadata"] or "{}"),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # checkpoints
    # ------------------------------------------------------------------

    def insert_checkpoint(self, checkpoint: Checkpoint) -> None:
        with self._write_lock:
            self._exec_txn(
                "INSERT INTO checkpoints (checkpoint_id, run_id, last_committed_sequence, "
                "task_state_revision, budget_state, pending_operations, file_snapshots, "
                "state_hash, schema_version, created_at, "
                "completed_node_id, last_action, next_node_id, checkpoint_registry_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._checkpoint_to_row(checkpoint),
            )

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE run_id = ? "
            "ORDER BY last_committed_sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_checkpoint(row)

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
    # Composite commit (SOP §5.3 atomic step)
    # ------------------------------------------------------------------

    def commit_runtime_step(
        self,
        *,
        run_id: str,
        conversation_id: str,
        event: SessionEvent,
        task_state_updates: Iterable[tuple[str, str, dict[str, Any]]] | None = None,
        context_items: Iterable[ContextItem] | None = None,
        snapshot: ContextSnapshot | None = None,
        checkpoint: Checkpoint | None = None,
    ) -> bool:
        """Apply one Runtime state commit atomically per SOP §5.3.

        The canonical order — event → task_state → context_items/snapshot →
        checkpoint — runs inside a single ``BEGIN IMMEDIATE ... COMMIT``
        transaction. If any step fails, the whole commit rolls back; partial
        state never reaches the database.

        Model calls, Bash, and file I/O MUST happen before this method is
        called; they must not hold the write transaction.

        Returns ``True`` if the event was newly committed, ``False`` if a
        duplicate ``event_id`` was detected (idempotent success — the prior
        commit's state is preserved, no other writes are applied).
        """
        validate_event(event)
        updates_list = list(task_state_updates) if task_state_updates else []
        items_list = list(context_items) if context_items else []
        for item in items_list:
            validate_item(item)

        with self._write_lock:
            # Idempotency precheck: if the event_id already exists, this is a
            # replay. Return False WITHOUT entering a transaction; the prior
            # commit's state is the source of truth.
            existing = self._conn.execute(
                "SELECT 1 FROM session_events WHERE event_id = ? "
                "OR (run_id = ? AND idempotency_key = ? AND idempotency_key IS NOT NULL)",
                (event.event_id, event.run_id, event.idempotency_key),
            ).fetchone()
            if existing is not None:
                return False

            try:
                self._conn.execute("BEGIN IMMEDIATE")

                # 1. Append SessionEvent.
                self._conn.execute(
                    "INSERT INTO session_events (event_id, conversation_id, run_id, "
                    "sequence, event_type, payload, created_at, schema_version, "
                    "turn_id, idempotency_key, payload_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.conversation_id,
                        event.run_id,
                        event.sequence,
                        event.event_type,
                        json.dumps(event.payload),
                        event.created_at,
                        int(event.schema_version),
                        event.turn_id,
                        event.idempotency_key,
                        event.payload_ref,
                    ),
                )

                # 2. Update materialized TaskState rows.
                for task_id, status, payload in updates_list:
                    self._upsert_task_state_locked(task_id, run_id, status, payload)

                # 3. Insert ContextItems and Snapshot (if produced this step).
                if items_list:
                    self._conn.executemany(
                        "INSERT INTO context_items (item_id, run_id, task_id, layer, kind, "
                        "content, source_type, source_ref, trust_level, source_created_sequence, "
                        "priority, scope, valid_from_sequence, valid_to_sequence, "
                        "supersedes_item_id, estimated_tokens, metadata, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [self._item_to_row(item) for item in items_list],
                    )

                if snapshot is not None:
                    self._conn.execute(
                        "INSERT INTO context_snapshots (snapshot_id, run_id, agent_id, role, "
                        "task_id, source_item_ids, excluded_items, rendered_hash, "
                        "estimated_tokens, estimator, created_sequence, created_at, session_id, "
                        "model_call_id, system_prompt_hash, static_prefix_hash, "
                        "selected_memory_ids, selected_artifact_locators, selected_event_ids, "
                        "event_range, compaction_summary_ref, omitted_counts, input_tokens, "
                        "policy_fingerprint) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                            snapshot.session_id,
                            snapshot.model_call_id,
                            snapshot.system_prompt_hash,
                            snapshot.static_prefix_hash,
                            json.dumps(list(snapshot.selected_memory_ids)),
                            json.dumps(list(snapshot.selected_artifact_locators)),
                            json.dumps(list(snapshot.selected_event_ids)),
                            json.dumps(snapshot.event_range, sort_keys=True),
                            snapshot.compaction_summary_ref,
                            json.dumps(snapshot.omitted_counts, sort_keys=True),
                            snapshot.input_tokens,
                            snapshot.policy_fingerprint,
                        ),
                    )

                # 4. Insert Checkpoint (only at safe step boundary).
                if checkpoint is not None:
                    self._conn.execute(
                        "INSERT INTO checkpoints (checkpoint_id, run_id, last_committed_sequence, "
                        "task_state_revision, budget_state, pending_operations, file_snapshots, "
                        "state_hash, schema_version, created_at, "
                        "completed_node_id, last_action, next_node_id, checkpoint_registry_hash) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        self._checkpoint_to_row(checkpoint),
                    )

                self._conn.execute("COMMIT")
            except sqlite3.Error:
                # Roll back the whole step. If rollback itself fails (connection
                # in a bad state), swallow so we always surface the original
                # error to the caller.
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            return True

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield the connection inside a single BEGIN IMMEDIATE transaction.

        Use this for composite writes that the granular methods do not cover.
        Long operations (model call, Bash, file I/O) MUST NOT run inside the
        yielded block; the writer lock is held for the whole context manager.

        RLock allows nesting, so a ``transaction()`` inside another
        ``transaction()`` reuses the outer transaction (no nested savepoints).
        """
        with self._write_lock:
            already_in_txn = self._conn.in_transaction
            if not already_in_txn:
                self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                if not already_in_txn:
                    self._conn.execute("COMMIT")
            except sqlite3.Error:
                if not already_in_txn:
                    try:
                        self._conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise

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
    def _checkpoint_to_row(checkpoint: Checkpoint) -> tuple[Any, ...]:
        """Serialize a Checkpoint to the row tuple matching the INSERT in
        ``insert_checkpoint`` / ``commit_runtime_step``.

        The four P0-C node-identity columns are appended after the original
        v1 columns. They are nullable; ``None`` maps to SQL NULL. This keeps
        the row layout stable for callers that read the v1 columns only.
        """
        return (
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
            checkpoint.completed_node_id,
            checkpoint.last_action,
            checkpoint.next_node_id,
            checkpoint.checkpoint_registry_hash,
        )

    @staticmethod
    def _memory_item_to_row(item: "MemoryItem") -> tuple[Any, ...]:
        return (
            item.memory_id,
            item.scope_type,
            item.scope_id,
            item.kind,
            item.content,
            json.dumps(list(item.source_refs), ensure_ascii=False),
            item.trust_level,
            int(item.importance),
            int(item.pinned),
            item.created_from_run_id,
            item.created_from_sequence,
            item.supersedes_memory_id,
            int(item.tombstone),
            item.content_hash,
            item.created_at,
        )

    @staticmethod
    def _row_to_checkpoint(row: sqlite3.Row) -> Checkpoint:
        """Reconstruct a Checkpoint from a ``checkpoints`` row.

        Uses ``row.keys()``-based access so the helper works whether the row
        was produced by ``SELECT *`` (includes v3 columns) or by a narrower
        projection (legacy callers). Missing P0-C columns default to None,
        matching the dataclass defaults.
        """
        keys = set(row.keys()) if hasattr(row, "keys") else set()
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
            completed_node_id=row["completed_node_id"] if "completed_node_id" in keys else None,
            last_action=row["last_action"] if "last_action" in keys else None,
            next_node_id=row["next_node_id"] if "next_node_id" in keys else None,
            checkpoint_registry_hash=(
                row["checkpoint_registry_hash"]
                if "checkpoint_registry_hash" in keys
                else None
            ),
        )

    @staticmethod
    def _row_to_memory_item(row: sqlite3.Row) -> "MemoryItem":
        from paperclaw.memory.contracts import MemoryItem

        return MemoryItem(
            memory_id=row["memory_id"],
            scope_type=row["scope_type"],
            scope_id=row["scope_id"],
            kind=row["kind"],
            content=row["content"],
            source_refs=tuple(json.loads(row["source_refs"])),
            trust_level=row["trust_level"],
            importance=int(row["importance"]),
            pinned=bool(row["pinned"]),
            created_from_run_id=row["created_from_run_id"],
            created_from_sequence=(
                int(row["created_from_sequence"])
                if row["created_from_sequence"] is not None
                else None
            ),
            supersedes_memory_id=row["supersedes_memory_id"],
            tombstone=bool(row["tombstone"]),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
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
