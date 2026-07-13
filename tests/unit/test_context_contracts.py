"""Phase A tests: Context contracts, SQLite migration, Repository basics.

Covers SOP §12 matrix entries:
- S-01 fresh migration v1 succeeds on empty database
- S-02 older schema is upgradeable, data preserved
- S-03 migration failure rolls back transaction, version not advanced
- S-05 duplicate event_id is idempotent (no duplicate state)
- S-06 sequence is strictly monotonic within a Run
- S-07 session reopen restores state and budget consistently

Plus contract-level invariants from §4 (frozen dataclasses, validators).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from paperclaw.context.contracts import (
    CONTEXT_KINDS,
    CONTEXT_LAYERS,
    SCOPE_COORDINATOR,
    SCOPE_REVIEWER,
    SCOPE_SHARED,
    TRUST_LEVELS,
    Checkpoint,
    CompactionResult,
    ContextBudget,
    ContextItem,
    ContextSnapshot,
    ContextSource,
    SessionEvent,
    SOURCE_TYPES,
    utc_now_iso,
    validate_event,
    validate_item,
    validate_source,
)
from paperclaw.context.migrations import (
    CURRENT_SCHEMA_VERSION,
    SCHEMA_VERSION_V1,
    V1_SCHEMA_SQL,
    MigrationRunner,
    MIGRATIONS,
    open_connection,
)
from paperclaw.context.repository import SQLiteRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a fresh SQLite file path under pytest's tmp_path."""
    return tmp_path / "context.db"


@pytest.fixture
def repo(tmp_db: Path) -> SQLiteRepository:
    """Open a repository with a per-test backup dir."""
    backup_dir = tmp_db.parent / "backups"
    r = SQLiteRepository(tmp_db, backup_dir=backup_dir, migrate=True)
    yield r
    r.close()


def _make_source(*, source_type: str = "runtime", trust_level: str = "system", sequence: int = 0) -> ContextSource:
    return ContextSource(
        source_type=source_type,
        source_ref=f"ref-{sequence}",
        trust_level=trust_level,
        created_sequence=sequence,
    )


def _make_item(
    *,
    item_id: str = "item-1",
    run_id: str = "run-1",
    layer: str = "L0",
    kind: str = "constraint",
    content: str = "do not bypass verify gate",
    scope: tuple[str, ...] = (SCOPE_SHARED,),
    priority: int = 100,
    estimated_tokens: int = 8,
    valid_from_sequence: int = 0,
    source: ContextSource | None = None,
    task_id: str | None = None,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        run_id=run_id,
        layer=layer,
        kind=kind,
        content=content,
        source=source or _make_source(sequence=valid_from_sequence),
        priority=priority,
        scope=scope,
        estimated_tokens=estimated_tokens,
        valid_from_sequence=valid_from_sequence,
        task_id=task_id,
    )


def _make_event(
    *,
    event_id: str = "evt-1",
    run_id: str = "run-1",
    conversation_id: str = "conv-1",
    sequence: int = 1,
    event_type: str = "task.assigned",
    payload: dict | None = None,
) -> SessionEvent:
    return SessionEvent(
        event_id=event_id,
        conversation_id=conversation_id,
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload or {"schema_version": 1, "task_id": "t1"},
        created_at=utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# Contract invariants
# ---------------------------------------------------------------------------


class TestContextContracts:
    """Frozen dataclasses & validators (SOP §4)."""

    def test_source_is_frozen(self):
        src = _make_source()
        with pytest.raises(Exception):
            src.source_type = "user"  # type: ignore[misc]

    def test_item_is_frozen(self):
        item = _make_item()
        with pytest.raises(Exception):
            item.content = "tampered"  # type: ignore[misc]

    def test_budget_usable_input(self):
        budget = ContextBudget(
            max_input_tokens=32000,
            reserved_output_tokens=6000,
            safety_margin_tokens=3200,
            max_single_item_tokens=8000,
            max_tool_output_tokens=8000,
        )
        assert budget.usable_input() == 32000 - 6000 - 3200

    def test_budget_safety_margin_floor_enforced(self):
        # 10% of 32000 = 3200. Anything lower must be rejected.
        with pytest.raises(ValueError, match="safety_margin_tokens"):
            ContextBudget(
                max_input_tokens=32000,
                reserved_output_tokens=6000,
                safety_margin_tokens=1000,  # < 10%
                max_single_item_tokens=8000,
                max_tool_output_tokens=8000,
            ).validate()

    def test_budget_non_positive_usable_rejected(self):
        with pytest.raises(ValueError, match="usable_input"):
            ContextBudget(
                max_input_tokens=5000,
                reserved_output_tokens=4000,
                safety_margin_tokens=1000,  # exactly 20% but usable=0
                max_single_item_tokens=1000,
                max_tool_output_tokens=1000,
            ).validate()

    def test_validate_source_rejects_unknown_trust(self):
        src = ContextSource(
            source_type="runtime",
            source_ref="r1",
            trust_level="root",  # not in TRUST_LEVELS
            created_sequence=0,
        )
        with pytest.raises(ValueError, match="trust_level"):
            validate_source(src)

    def test_validate_source_rejects_unknown_source_type(self):
        src = ContextSource(
            source_type="aux",
            source_ref="r1",
            trust_level="system",
            created_sequence=0,
        )
        with pytest.raises(ValueError, match="source_type"):
            validate_source(src)

    def test_validate_item_rejects_bad_layer(self):
        item = ContextItem(
            item_id="i1",
            run_id="r1",
            layer="L9",
            kind="constraint",
            content="x",
            source=_make_source(),
            priority=1,
            scope=(SCOPE_SHARED,),
            estimated_tokens=1,
            valid_from_sequence=0,
        )
        with pytest.raises(ValueError, match="layer"):
            validate_item(item)

    def test_validate_item_rejects_inverted_validity_window(self):
        item = ContextItem(
            item_id="i1",
            run_id="r1",
            layer="L3",
            kind="todo",
            content="x",
            source=_make_source(),
            priority=1,
            scope=(SCOPE_SHARED,),
            estimated_tokens=1,
            valid_from_sequence=5,
            valid_to_sequence=3,
        )
        with pytest.raises(ValueError, match="valid_to_sequence"):
            validate_item(item)

    def test_validate_item_rejects_empty_scope(self):
        item = ContextItem(
            item_id="i1",
            run_id="r1",
            layer="L0",
            kind="constraint",
            content="x",
            source=_make_source(),
            priority=1,
            scope=(),
            estimated_tokens=1,
            valid_from_sequence=0,
        )
        with pytest.raises(ValueError, match="scope"):
            validate_item(item)

    def test_item_is_active_at(self):
        item = _make_item(valid_from_sequence=2, item_id="i-active")
        assert not item.is_active_at(1)
        assert item.is_active_at(2)
        assert item.is_active_at(5)

    def test_item_with_valid_to_inactive(self):
        item = ContextItem(
            item_id="i2",
            run_id="r1",
            layer="L3",
            kind="todo",
            content="x",
            source=_make_source(),
            priority=1,
            scope=(SCOPE_SHARED,),
            estimated_tokens=1,
            valid_from_sequence=2,
            valid_to_sequence=5,
        )
        assert item.is_active_at(4)
        assert not item.is_active_at(5)
        assert not item.is_active_at(10)

    def test_event_requires_schema_version_in_payload(self):
        bad = SessionEvent(
            event_id="e1",
            conversation_id="c1",
            run_id="r1",
            sequence=1,
            event_type="x.y",
            payload={"no_version": True},
            created_at=utc_now_iso(),
        )
        with pytest.raises(ValueError, match="schema_version"):
            validate_event(bad)

    def test_snapshot_to_dict_round_trip(self):
        snap = ContextSnapshot(
            snapshot_id="s1",
            run_id="r1",
            agent_id="a1",
            role="coordinator",
            source_item_ids=("i1", "i2"),
            excluded_items=({"item_id": "i3", "exclusion_reason": "scope"},),
            rendered_hash="abc",
            estimated_tokens=200,
            estimator="char4",
            created_sequence=3,
        )
        d = snap.to_dict()
        assert d["source_item_ids"] == ["i1", "i2"]
        assert d["excluded_items"] == [{"item_id": "i3", "exclusion_reason": "scope"}]

    def test_checkpoint_to_dict_round_trip(self):
        cp = Checkpoint(
            checkpoint_id="cp1",
            run_id="r1",
            last_committed_sequence=7,
            task_state_revision=2,
            budget_state={"steps_used": 5},
            pending_operations=({"operation_id": "op1", "status": "started"},),
            file_snapshots=({"path": "x", "hash": "h1"},),
            state_hash="state-abc",
            schema_version=SCHEMA_VERSION_V1,
            created_at=utc_now_iso(),
        )
        d = cp.to_dict()
        assert d["pending_operations"][0]["operation_id"] == "op1"
        assert d["file_snapshots"][0]["path"] == "x"

    def test_compaction_result_is_frozen(self):
        result = CompactionResult(
            summary_item_ids=("s1",),
            retained_constraint_ids=("c1",),
            retained_evidence_refs=("e1",),
            removed_item_ids=("r1",),
            source_item_ids=("o1",),
            compaction_hash="hash1",
        )
        with pytest.raises(Exception):
            result.compaction_hash = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestMigrations:
    """SOP §12: S-01 fresh migration, S-02 upgrade, S-03 rollback on failure."""

    def test_s01_fresh_migration_v1_succeeds(self, tmp_db: Path):
        # S-01: empty database, migration v1 succeeds.
        conn = open_connection(tmp_db)
        runner = MigrationRunner(conn)
        result = runner.migrate(make_backup=False)
        assert result.ok, f"migration failed: {result.error}"
        assert result.applied_version == SCHEMA_VERSION_V1
        assert not result.already_at_version

        # All v1 tables must exist.
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cur.fetchall()}
        expected = {
            "schema_migrations",
            "conversations",
            "runs",
            "session_events",
            "messages",
            "task_states",
            "context_items",
            "context_snapshots",
            "checkpoints",
            "idempotency_ledger",
        }
        assert expected.issubset(tables), f"missing tables: {expected - tables}"
        conn.close()

    def test_migration_is_idempotent(self, tmp_db: Path):
        conn = open_connection(tmp_db)
        runner = MigrationRunner(conn)
        first = runner.migrate(make_backup=False)
        second = runner.migrate(make_backup=False)
        assert first.ok
        assert second.ok
        assert second.already_at_version is True
        conn.close()

    def test_s02_upgrade_preserves_data(self, tmp_db: Path):
        # S-02: simulate a "pre-migration" state by manually creating an
        # empty database (version 0) with one pre-existing row in a table
        # that v1 creates with IF NOT EXISTS. After migration, data persists.
        conn = open_connection(tmp_db)
        # Manually create schema_migrations with version=0 (no tables yet).
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)"
        )
        conn.execute("INSERT INTO schema_migrations VALUES (0, '1970', 'pre')")
        # Run migration: should reach v1.
        runner = MigrationRunner(conn)
        result = runner.migrate(make_backup=False)
        assert result.ok
        assert result.applied_version == SCHEMA_VERSION_V1
        # Verify the v0 row is preserved AND v1 row exists.
        cur = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cur.fetchall()]
        assert versions == [0, 1]
        conn.close()

    def test_s03_migration_failure_rolls_back_version(self, tmp_db: Path):
        # S-03: Inject a broken DDL after the legit v1 DDL to force a failure.
        # We register a fake v2 migration with invalid SQL; schema_version
        # must remain at 1 (the prior version).
        conn = open_connection(tmp_db)
        runner = MigrationRunner(conn)
        first = runner.migrate(make_backup=False)
        assert first.ok

        # Inject a fake broken migration into the global registry.
        original = MIGRATIONS.copy()
        MIGRATIONS[2] = ("broken", ("THIS IS NOT VALID SQL;",))
        try:
            runner2 = MigrationRunner(conn)
            result = runner2.migrate(make_backup=False)
            assert not result.ok
            assert result.error is not None
            # Version must NOT advance past 1.
            assert runner2.current_version() == 1
        finally:
            MIGRATIONS.clear()
            MIGRATIONS.update(original)
        conn.close()

    def test_backup_is_created_when_backup_dir_set(self, tmp_db: Path, tmp_path: Path):
        backup_dir = tmp_path / "backups"
        # First open + migrate to v1 (no backup because empty file).
        repo = SQLiteRepository(tmp_db, backup_dir=backup_dir, migrate=True)
        repo.close()

        # Re-open the SAME db file (now at v1) with a fake v2 migration that
        # is valid; backup should be created before upgrade.
        from paperclaw.context.migrations import MIGRATIONS, V1_SCHEMA_SQL

        original = MIGRATIONS.copy()
        # Create a new "v2" migration that adds a column to conversations.
        MIGRATIONS[2] = (
            "add column v2",
            ("ALTER TABLE conversations ADD COLUMN extra TEXT;",),
        )
        try:
            conn = open_connection(tmp_db)
            runner = MigrationRunner(conn, backup_dir=backup_dir)
            result = runner.migrate(make_backup=True)
            assert result.ok
            assert result.backup_path is not None
            assert Path(result.backup_path).exists()
            conn.close()
        finally:
            MIGRATIONS.clear()
            MIGRATIONS.update(original)

    def test_open_connection_enables_wal(self, tmp_db: Path):
        conn = open_connection(tmp_db)
        cur = conn.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        assert mode.lower() == "wal"
        # busy_timeout must be > 0
        bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert int(bt) > 0
        # foreign_keys ON
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert int(fk) == 1
        conn.close()


# ---------------------------------------------------------------------------
# Repository basics
# ---------------------------------------------------------------------------


class TestRepositoryBasics:
    """Append-only events, sequence monotonicity, idempotency, reopen."""

    def test_next_sequence_starts_at_one(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        assert repo.next_sequence("run-1") == 1
        assert repo.next_sequence("run-1") == 1  # not yet appended

    def test_s06_sequence_strictly_monotonic(self, repo: SQLiteRepository):
        # SOP S-06: sequence strictly monotonic within a Run.
        # ``next_sequence`` is a peek (does not reserve). Monotonicity is
        # enforced by the (run_id, sequence) UNIQUE constraint when an event
        # is actually appended. Each append must advance MAX(sequence).
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        seqs: list[int] = []
        for i in range(1, 6):
            seq = repo.next_sequence("run-1")
            seqs.append(seq)
            assert seq == i, f"peek before append #{i} returned {seq}"
            repo.append_event(
                _make_event(event_id=f"e-{i}", run_id="run-1", sequence=seq)
            )
        assert seqs == [1, 2, 3, 4, 5]
        # After 5 appends, next peek must be 6.
        assert repo.next_sequence("run-1") == 6

    def test_append_event_returns_true_on_first_write(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        ev = _make_event(event_id="e1", run_id="run-1", conversation_id="conv-1", sequence=1)
        assert repo.append_event(ev) is True

    def test_s05_duplicate_event_id_is_idempotent(self, repo: SQLiteRepository):
        # SOP S-05: duplicate event_id must not produce duplicate state.
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        ev = _make_event(event_id="dup-1", run_id="run-1", conversation_id="conv-1", sequence=1)
        assert repo.append_event(ev) is True
        # Re-append the same event_id (even with different payload): must
        # return False and NOT create a new row.
        duplicate = _make_event(
            event_id="dup-1",
            run_id="run-1",
            conversation_id="conv-1",
            sequence=1,
            payload={"schema_version": 1, "tampered": True},
        )
        assert repo.append_event(duplicate) is False
        events = repo.list_events("run-1")
        assert len(events) == 1
        # Original payload preserved.
        assert events[0].payload.get("tampered") is None

    def test_duplicate_run_sequence_integrity_error(self, repo: SQLiteRepository):
        # Same run_id + sequence with a different event_id must raise
        # IntegrityError (real bug, not idempotent success).
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        e1 = _make_event(event_id="e-1", run_id="run-1", sequence=1)
        e2 = _make_event(event_id="e-2", run_id="run-1", sequence=1)
        repo.append_event(e1)
        with pytest.raises(sqlite3.IntegrityError):
            repo.append_event(e2)

    def test_list_events_orders_by_sequence(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        for i in range(1, 4):
            repo.append_event(_make_event(event_id=f"e-{i}", run_id="run-1", sequence=i))
        listed = repo.list_events("run-1")
        assert [e.sequence for e in listed] == [1, 2, 3]
        # since_sequence filter
        listed_since_2 = repo.list_events("run-1", since_sequence=1)
        assert [e.sequence for e in listed_since_2] == [2, 3]

    def test_last_committed_sequence(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        assert repo.last_committed_sequence("run-1") == 0
        repo.append_event(_make_event(event_id="e-1", run_id="run-1", sequence=1))
        assert repo.last_committed_sequence("run-1") == 1

    # ------------------------------------------------------------------
    # S-07 reopen
    # ------------------------------------------------------------------

    def test_s07_session_reopen_restores_state(self, tmp_db: Path):
        # S-07: close and reopen; events and task state must be intact.
        repo1 = SQLiteRepository(tmp_db, migrate=True)
        repo1.create_conversation("conv-1")
        repo1.start_run("run-1", "conv-1", "agent-1", "coordinator")
        repo1.append_event(_make_event(event_id="e-1", run_id="run-1", sequence=1))
        repo1.append_event(_make_event(event_id="e-2", run_id="run-1", sequence=2))
        repo1.upsert_task_state("task-1", "run-1", "pending", {"assignee": "w1"})
        repo1.close()

        repo2 = SQLiteRepository(tmp_db, migrate=True)
        events = repo2.list_events("run-1")
        assert [e.sequence for e in events] == [1, 2]
        ts = repo2.get_task_state("task-1")
        assert ts is not None
        assert ts["status"] == "pending"
        assert ts["payload"]["assignee"] == "w1"
        assert ts["revision"] == 0
        # next sequence continues from 2.
        assert repo2.next_sequence("run-1") == 3
        repo2.close()

    # ------------------------------------------------------------------
    # Idempotency ledger
    # ------------------------------------------------------------------

    def test_idempotency_first_call_returns_true(self, repo: SQLiteRepository):
        assert repo.record_idempotent_operation("op-1", "bash.execute", "h1") is True

    def test_idempotency_second_call_returns_false(self, repo: SQLiteRepository):
        assert repo.record_idempotent_operation("op-2", "bash.execute", "h2") is True
        assert repo.record_idempotent_operation("op-2", "bash.execute", "h2") is False

    # ------------------------------------------------------------------
    # Task state revision
    # ------------------------------------------------------------------

    def test_task_state_revision_bumps_on_update(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        r1 = repo.upsert_task_state("t1", "run-1", "pending", {"a": 1})
        r2 = repo.upsert_task_state("t1", "run-1", "running", {"a": 2})
        r3 = repo.upsert_task_state("t1", "run-1", "completed", {"a": 3})
        assert (r1, r2, r3) == (0, 1, 2)

    def test_task_state_no_revision_bump_when_disabled(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        repo.upsert_task_state("t1", "run-1", "pending", {"a": 1})
        r2 = repo.upsert_task_state("t1", "run-1", "pending", {"a": 2}, bump_revision=False)
        assert r2 == 0  # revision not advanced

    # ------------------------------------------------------------------
    # Context items
    # ------------------------------------------------------------------

    def test_insert_and_get_context_item(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        item = _make_item(item_id="ci-1", run_id="run-1", valid_from_sequence=1)
        repo.insert_context_item(item)
        fetched = repo.get_context_item("ci-1")
        assert fetched is not None
        assert fetched.item_id == "ci-1"
        assert fetched.source.source_type == "runtime"
        assert fetched.scope == (SCOPE_SHARED,)

    def test_list_context_items_filters_by_layer(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        repo.insert_context_items(
            [
                _make_item(item_id="ci-L0", run_id="run-1", layer="L0", valid_from_sequence=1),
                _make_item(item_id="ci-L3", run_id="run-1", layer="L3", valid_from_sequence=1),
                _make_item(item_id="ci-L4", run_id="run-1", layer="L4", valid_from_sequence=1),
            ]
        )
        l3 = repo.list_context_items("run-1", layer="L3")
        assert [i.item_id for i in l3] == ["ci-L3"]

    def test_list_context_items_at_sequence(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        # i1 active [1, None); i2 active [1, 5); i3 active [3, None)
        repo.insert_context_items(
            [
                _make_item(item_id="i1", run_id="run-1", valid_from_sequence=1),
                ContextItem(
                    item_id="i2",
                    run_id="run-1",
                    layer="L3",
                    kind="todo",
                    content="x",
                    source=_make_source(sequence=1),
                    priority=1,
                    scope=(SCOPE_SHARED,),
                    estimated_tokens=1,
                    valid_from_sequence=1,
                    valid_to_sequence=5,
                ),
                _make_item(item_id="i3", run_id="run-1", valid_from_sequence=3),
            ]
        )
        at_2 = repo.list_context_items("run-1", at_sequence=2)
        ids = {i.item_id for i in at_2}
        assert ids == {"i1", "i2"}  # i3 not yet active
        at_5 = repo.list_context_items("run-1", at_sequence=5)
        ids5 = {i.item_id for i in at_5}
        assert ids5 == {"i1", "i3"}  # i2 expired at sequence 5

    # ------------------------------------------------------------------
    # Snapshots & checkpoints
    # ------------------------------------------------------------------

    def test_insert_and_list_snapshots(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        snap = ContextSnapshot(
            snapshot_id="s1",
            run_id="run-1",
            agent_id="a1",
            role="coordinator",
            source_item_ids=("i1", "i2"),
            excluded_items=({"item_id": "i3", "exclusion_reason": "scope"},),
            rendered_hash="abc",
            estimated_tokens=200,
            estimator="char4",
            created_sequence=2,
        )
        repo.insert_snapshot(snap)
        snaps = repo.list_snapshots("run-1")
        assert len(snaps) == 1
        assert snaps[0].source_item_ids == ("i1", "i2")
        assert snaps[0].estimator == "char4"

    def test_insert_and_latest_checkpoint(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        cp1 = Checkpoint(
            checkpoint_id="cp1",
            run_id="run-1",
            last_committed_sequence=3,
            task_state_revision=1,
            budget_state={"steps_used": 2},
            pending_operations=(),
            file_snapshots=(),
            state_hash="h-3",
            schema_version=SCHEMA_VERSION_V1,
            created_at=utc_now_iso(),
        )
        cp2 = Checkpoint(
            checkpoint_id="cp2",
            run_id="run-1",
            last_committed_sequence=7,
            task_state_revision=2,
            budget_state={"steps_used": 5},
            pending_operations=(),
            file_snapshots=(),
            state_hash="h-7",
            schema_version=SCHEMA_VERSION_V1,
            created_at=utc_now_iso(),
        )
        repo.insert_checkpoint(cp1)
        repo.insert_checkpoint(cp2)
        latest = repo.latest_checkpoint("run-1")
        assert latest is not None
        assert latest.checkpoint_id == "cp2"
        assert latest.last_committed_sequence == 7

    def test_latest_checkpoint_returns_none_for_empty_run(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        assert repo.latest_checkpoint("run-1") is None

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def test_append_and_list_messages(self, repo: SQLiteRepository):
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
        repo.append_message("m1", "conv-1", "run-1", "user", "hello", 1)
        repo.append_message("m2", "conv-1", "run-1", "assistant", "hi", 2)
        msgs = repo.list_messages("conv-1")
        assert [m["sequence"] for m in msgs] == [1, 2]
        assert msgs[0]["role"] == "user"
        assert msgs[1]["content"] == "hi"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestRepositoryConcurrency:
    """S-04: concurrent writers must not lose events or surface database-locked.

    The writer lock serializes ``append_event`` calls; SQLite's own busy_timeout
    handles the rare case where two connections (different processes) try to
    write at the same time. Within a single Repository instance, the in-process
    lock is the primary defense.
    """

    def test_s04_concurrent_appends_no_loss(self, tmp_db: Path):
        repo = SQLiteRepository(tmp_db, migrate=True)
        repo.create_conversation("conv-1")
        repo.start_run("run-1", "conv-1", "agent-1", "coordinator")

        N_THREADS = 8
        N_PER_THREAD = 25
        errors: list[BaseException] = []
        appended_counts: list[int] = []

        def writer(thread_idx: int):
            try:
                count = 0
                for j in range(N_PER_THREAD):
                    # Use the atomic allocate-and-append path; the peek +
                    # append pattern is NOT safe across threads.
                    appended, _ = repo.append_event_with_auto_sequence(
                        event_id=f"e-t{thread_idx}-{j}",
                        conversation_id="conv-1",
                        run_id="run-1",
                        event_type="task.progress",
                        payload={"schema_version": 1, "thread": thread_idx, "j": j},
                    )
                    if appended:
                        count += 1
                appended_counts.append(count)
            except BaseException as exc:  # noqa: BLE001 - re-raised in main thread
                errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(i,), daemon=True)
            for i in range(N_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == [], f"writers raised: {errors}"
        total_appended = sum(appended_counts)
        expected = N_THREADS * N_PER_THREAD
        assert total_appended == expected, (
            f"lost events: appended {total_appended} of {expected}"
        )
        events = repo.list_events("run-1")
        assert len(events) == expected
        # Sequences must be 1..N strictly monotonic with no gaps or duplicates.
        seqs = sorted(e.sequence for e in events)
        assert seqs == list(range(1, expected + 1))
        # No duplicate event_ids.
        ids = [e.event_id for e in events]
        assert len(set(ids)) == len(ids)
        repo.close()
