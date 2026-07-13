"""SQLite schema migrations for the v0.04 Context Runtime.

Design rules (SOP §5.3):

- Each migration runs in its own transaction. If it fails, schema_version
  MUST NOT advance.
- Migrations are forward-only in v0.04. Down-migrations are not provided;
  backups are taken before upgrade instead.
- ``schema_migrations`` is the authoritative version table.

The v1 schema creates the minimal table set defined in SOP §5.1:

    schema_migrations
    conversations
    runs
    session_events
    messages
    task_states
    context_items
    context_snapshots
    checkpoints
    idempotency_ledger

``memory_items`` is intentionally omitted (deferred to a later version).
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION_V1 = 1

#: Current target schema version after applying all known migrations.
CURRENT_SCHEMA_VERSION = SCHEMA_VERSION_V1


@dataclass
class MigrationResult:
    """Outcome of one migration attempt."""

    applied_version: int
    backup_path: str | None
    already_at_version: bool
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Schema DDL (v1)
# ---------------------------------------------------------------------------

#: SQL to create the v1 schema. Each statement is independently executable;
#: the whole list runs inside a single transaction so partial failures roll back.
V1_SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version         INTEGER PRIMARY KEY,
        applied_at      TEXT NOT NULL,
        description     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        conversation_id TEXT PRIMARY KEY,
        created_at      TEXT NOT NULL,
        metadata        TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id              TEXT PRIMARY KEY,
        conversation_id     TEXT NOT NULL,
        agent_id            TEXT NOT NULL,
        role                TEXT NOT NULL,
        task_id             TEXT,
        created_at          TEXT NOT NULL,
        ended_at            TEXT,
        stop_reason         TEXT,
        metadata            TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_events (
        event_id            TEXT PRIMARY KEY,
        conversation_id     TEXT NOT NULL,
        run_id              TEXT NOT NULL,
        sequence            INTEGER NOT NULL,
        event_type          TEXT NOT NULL,
        payload             TEXT NOT NULL,
        created_at          TEXT NOT NULL,
        schema_version      INTEGER NOT NULL,
        UNIQUE (run_id, sequence),
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_session_events_run_seq
        ON session_events (run_id, sequence)
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        message_id          TEXT PRIMARY KEY,
        conversation_id     TEXT NOT NULL,
        run_id              TEXT NOT NULL,
        role                TEXT NOT NULL,
        content             TEXT NOT NULL,
        sequence            INTEGER NOT NULL,
        created_at          TEXT NOT NULL,
        metadata            TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id),
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_states (
        task_id             TEXT PRIMARY KEY,
        run_id              TEXT NOT NULL,
        status              TEXT NOT NULL,
        revision            INTEGER NOT NULL DEFAULT 0,
        payload             TEXT NOT NULL DEFAULT '{}',
        updated_at          TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_items (
        item_id                 TEXT PRIMARY KEY,
        run_id                  TEXT NOT NULL,
        task_id                 TEXT,
        layer                   TEXT NOT NULL,
        kind                    TEXT NOT NULL,
        content                 TEXT NOT NULL,
        source_type             TEXT NOT NULL,
        source_ref              TEXT NOT NULL,
        trust_level             TEXT NOT NULL,
        source_created_sequence INTEGER NOT NULL,
        priority                INTEGER NOT NULL,
        scope                   TEXT NOT NULL,
        valid_from_sequence     INTEGER NOT NULL,
        valid_to_sequence       INTEGER,
        supersedes_item_id      TEXT,
        estimated_tokens        INTEGER NOT NULL,
        metadata                TEXT NOT NULL DEFAULT '{}',
        created_at              TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_context_items_run_seq
        ON context_items (run_id, valid_from_sequence)
    """,
    """
    CREATE TABLE IF NOT EXISTS context_snapshots (
        snapshot_id         TEXT PRIMARY KEY,
        run_id              TEXT NOT NULL,
        agent_id            TEXT NOT NULL,
        role                TEXT NOT NULL,
        task_id             TEXT,
        source_item_ids     TEXT NOT NULL,
        excluded_items      TEXT NOT NULL,
        rendered_hash       TEXT NOT NULL,
        estimated_tokens    INTEGER NOT NULL,
        estimator           TEXT NOT NULL,
        created_sequence    INTEGER NOT NULL,
        created_at          TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS checkpoints (
        checkpoint_id           TEXT PRIMARY KEY,
        run_id                  TEXT NOT NULL,
        last_committed_sequence INTEGER NOT NULL,
        task_state_revision     INTEGER NOT NULL,
        budget_state            TEXT NOT NULL,
        pending_operations      TEXT NOT NULL,
        file_snapshots          TEXT NOT NULL,
        state_hash              TEXT NOT NULL,
        schema_version          INTEGER NOT NULL,
        created_at              TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_ledger (
        operation_id            TEXT PRIMARY KEY,
        run_id                  TEXT,
        event_type              TEXT NOT NULL,
        payload_hash            TEXT NOT NULL,
        first_seen_at           TEXT NOT NULL,
        last_seen_at            TEXT NOT NULL,
        seen_count              INTEGER NOT NULL DEFAULT 1
    )
    """,
)


#: Map schema_version -> (description, DDL tuple). Used by MigrationRunner.
MIGRATIONS: dict[int, tuple[str, tuple[str, ...]]] = {
    SCHEMA_VERSION_V1: ("initial v0.04 context runtime schema", V1_SCHEMA_SQL),
}


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


class MigrationRunner:
    """Apply forward-only SQLite migrations in independent transactions.

    Each migration is wrapped in BEGIN IMMEDIATE / COMMIT. If any statement
    fails, the transaction rolls back and ``schema_migrations.version`` is NOT
    advanced, leaving the database at the prior version.

    Before upgrading from version N to N+1, the caller may request a file
    backup. The backup is a plain file copy; v0.04 does not provide
    down-migrations.
    """

    def __init__(self, connection: sqlite3.Connection, backup_dir: Path | None = None):
        self._conn = connection
        self._backup_dir = backup_dir

    def current_version(self) -> int:
        """Return the current schema_version, or 0 if no migrations applied."""
        try:
            cur = self._conn.execute(
                "SELECT MAX(version) FROM schema_migrations"
            )
            row = cur.fetchone()
        except sqlite3.OperationalError:
            # schema_migrations table doesn't exist yet → fresh database.
            return 0
        return int(row[0]) if row and row[0] is not None else 0

    def target_version(self) -> int:
        return max(MIGRATIONS.keys()) if MIGRATIONS else 0

    def migrate(self, target_version: int | None = None, make_backup: bool = True) -> MigrationResult:
        """Apply migrations up to ``target_version`` (default: latest).

        ``make_backup=True`` copies the SQLite file to ``backup_dir`` before
        the first migration that actually applies. Fresh databases (current
        version 0 with no file yet) skip the backup.
        """
        target = target_version or self.target_version()
        current = self.current_version()
        if current >= target:
            return MigrationResult(
                applied_version=current,
                backup_path=None,
                already_at_version=True,
                error=None,
            )

        backup_path = self._maybe_make_backup(current) if make_backup else None

        for version in range(current + 1, target + 1):
            description, ddl = MIGRATIONS.get(version, (None, None))
            if ddl is None:
                return MigrationResult(
                    applied_version=current,
                    backup_path=backup_path,
                    already_at_version=False,
                    error=f"no migration registered for version {version}",
                )
            error = self._apply_one(version, description, ddl)
            if error is not None:
                # Transaction rolled back; schema_version unchanged.
                return MigrationResult(
                    applied_version=current,
                    backup_path=backup_path,
                    already_at_version=False,
                    error=error,
                )
            current = version

        return MigrationResult(
            applied_version=current,
            backup_path=backup_path,
            already_at_version=False,
            error=None,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _maybe_make_backup(self, current_version: int) -> str | None:
        """Copy the SQLite file to ``backup_dir`` if a path is configured.

        We can only back up file-backed databases. In-memory connections
        (``:memory:``) return None and proceed without backup; callers that
        need backups must pass a file path when opening the connection.
        """
        if self._backup_dir is None:
            return None
        # ``sqlite3`` does not expose the file path; we rely on the caller
        # having opened the connection with a real file path. We detect this
        # by attempting to query the database file size via pragma.
        try:
            cur = self._conn.execute("PRAGMA database_list")
            row = cur.fetchone()
        except sqlite3.Error:
            return None
        if not row or row[2] in (None, ""):
            # in-memory or temporary database
            return None
        db_path = Path(row[2])
        if not db_path.exists():
            return None
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        from paperclaw.context.contracts import utc_now_iso

        stamp = utc_now_iso().replace(":", "").replace("-", "").split(".")[0]
        backup_name = f"{db_path.stem}.v{current_version}.bak-{stamp}{db_path.suffix}"
        backup_path = self._backup_dir / backup_name
        shutil.copy2(db_path, backup_path)
        return str(backup_path)

    def _apply_one(self, version: int, description: str, ddl: tuple[str, ...]) -> str | None:
        """Apply one migration in a single IMMEDIATE transaction.

        Returns ``None`` on success or an error message. On any sqlite3.Error
        the transaction is rolled back; ``schema_migrations`` is NOT updated.
        """
        from paperclaw.context.contracts import utc_now_iso

        try:
            # BEGIN IMMEDIATE acquires a write lock up-front so concurrent
            # writers fail fast instead of waiting for busy_timeout.
            self._conn.execute("BEGIN IMMEDIATE")
            for statement in ddl:
                # Strip trailing semicolons / whitespace; sqlite3.execute wants
                # exactly one statement per call.
                self._conn.execute(statement)
            self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at, description) "
                "VALUES (?, ?, ?)",
                (version, utc_now_iso(), description),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error as exc:
            # Roll back may itself raise if the connection is in a bad state;
            # guard it so we always return the original error.
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return str(exc)
        return None


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------


def open_connection(db_path: str | Path, *, wal: bool = True, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    """Open a SQLite connection with v0.04 SOP §5.4 defaults.

    - WAL mode for concurrent readers + single writer.
    - ``busy_timeout`` so transient lock contention does not fail immediately.
    - Foreign keys enforced (cascades and FK checks are part of the schema).
    - ``check_same_thread=False`` because the Repository serializes writes
      itself; callers should still use a single writer queue.
    """
    path = str(db_path)
    # ``isolation_level=None`` enables autocommit; we explicitly use BEGIN
    # IMMEDIATE / COMMIT in Repository transactions so we want manual control.
    conn = sqlite3.connect(
        path,
        isolation_level=None,
        check_same_thread=False,
        timeout=busy_timeout_ms / 1000.0,
    )
    conn.row_factory = sqlite3.Row
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
