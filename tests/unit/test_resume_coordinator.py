"""Phase E end-to-end tests for ResumeCoordinator and FileSnapshotVerifier.

Covers SOP §12 test matrix R-01 through R-06 for safe resume decisions:

- R-01: Step-boundary resume from a clean checkpoint → ``ok``.
- R-02: Pending Bash operation (``operation.started``, no terminal event)
  → ``recovery_required`` (NEVER auto-replay).
- R-03: Pending file_write operation (``operation.started``, no terminal)
  → ``recovery_required``.
- R-04: External file change detected by ``FileSnapshotVerifier`` →
  ``recovery_required`` with ``file_conflicts`` populated.
- R-05: Missing checkpoint → ``recovery_required`` mentioning
  "no Checkpoint exists".
- R-06: Active Worker marker (TaskState status="active") →
  ``recovery_required`` (v0.04 detects but does not recover; SOP §10.3).

Additional coverage:

- ``build_pending_operations`` event-log reconstruction: empty events,
  started-only, started+committed, started+failed, started+unknown_outcome,
  retry (multiple started), terminal without started, malformed events
  (missing ``operation_id``).
- ``FileSnapshotVerifier.verify`` with: existing file matches, hash mismatch,
  file missing when required, file missing when not required (absence
  snapshot), file exists when snapshot recorded absence.
- ``FileSnapshotVerifier.snapshot`` round-trip: snapshot → verify matches;
  modify file → verify returns False.
- ``ResumeCoordinator.decide_resume`` with pre-computed
  ``pending_operations`` parameter (skips event-log reconstruction).
- Schema version gate: ``schema_version=99`` → ``recovery_required``.
"""

from __future__ import annotations

from typing import Any

import pytest
from pocketflow import Node

from paperclaw.context.contracts import Checkpoint, SessionEvent, utc_now_iso
from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.runtime import (
    FileSnapshotVerifier,
    NodeRegistry,
    ResumeCoordinator,
    build_pending_operations,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class TraceNode(Node):
    """Minimal ``pocketflow.Node`` subclass exposing a ``node_id``.

    Kept local (not imported from another test module) so this test file is
    self-contained, mirroring the convention in ``test_checkpoint_wiring.py``.
    The NodeRegistry requires nodes to carry a ``node_id`` attribute; the
    actual ``prep``/``exec``/``post`` logic is irrelevant for resume-safety
    tests because the coordinator never enters a node — it only reads
    registry membership and hash.
    """

    def __init__(self, node_id: str, action: str | None = "default") -> None:
        super().__init__()
        self.node_id = node_id
        self._action = action

    def prep(self, shared: dict) -> Any:
        return None

    def exec(self, prep_res: Any) -> Any:
        return None

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        return self._action


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_checkpoint(
    *,
    run_id: str = "run-test",
    last_committed_sequence: int = 1,
    completed_node_id: str | None = None,
    last_action: str | None = None,
    next_node_id: str | None = None,
    checkpoint_registry_hash: str | None = None,
    pending_operations: tuple[dict[str, Any], ...] = (),
    file_snapshots: tuple[dict[str, Any], ...] = (),
    schema_version: int = 1,
    task_state_revision: int = 0,
) -> Checkpoint:
    """Synthesize a ``Checkpoint`` for resume-coordinator tests.

    Uses deterministic defaults so tests do not depend on wall-clock time
    for assertions (``created_at`` is set but never asserted on).
    """
    return Checkpoint(
        checkpoint_id=f"cp-test-{last_committed_sequence}",
        run_id=run_id,
        last_committed_sequence=last_committed_sequence,
        task_state_revision=task_state_revision,
        budget_state={},
        pending_operations=pending_operations,
        file_snapshots=file_snapshots,
        state_hash="state-hash-test",
        schema_version=schema_version,
        created_at=utc_now_iso(),
        completed_node_id=completed_node_id,
        last_action=last_action,
        next_node_id=next_node_id,
        checkpoint_registry_hash=checkpoint_registry_hash,
    )


def _make_event(
    *,
    event_type: str,
    operation_id: str,
    sequence: int = 1,
    run_id: str = "run-test",
    conversation_id: str = "conv-test",
    created_at: str | None = None,
) -> SessionEvent:
    """Build a ``SessionEvent`` for ``build_pending_operations`` tests.

    Constructs the dataclass directly (bypassing the repository) so tests
    are deterministic and do not require a SQLite fixture.
    """
    return SessionEvent(
        event_id=f"evt-{operation_id}-{event_type}-{sequence}",
        conversation_id=conversation_id,
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        payload={"operation_id": operation_id, "schema_version": 1},
        created_at=created_at or utc_now_iso(),
    )


def _emit_operation(
    repo: SQLiteRepository,
    *,
    event_type: str,
    operation_id: str,
    run_id: str = "run-test",
    conversation_id: str = "conv-test",
) -> None:
    """Insert an ``operation.*`` event via the repository.

    Wraps ``append_event_with_auto_sequence`` (keyword-only) so tests can
    emit events with a concise call. The sequence is auto-assigned by the
    repository, preserving monotonicity without the test computing it.
    """
    repo.append_event_with_auto_sequence(
        event_id=f"evt-{operation_id}-{event_type}",
        conversation_id=conversation_id,
        run_id=run_id,
        event_type=event_type,
        payload={"operation_id": operation_id, "schema_version": 1},
    )


def _build_registry(node_ids: list[str]) -> NodeRegistry:
    """Build a ``NodeRegistry`` with ``TraceNode`` entries.

    Each node gets a ``node_id`` from ``node_ids``; the registry hash is
    computed from the sorted node-id set, so two registries with the same
    ids produce the same hash (deterministic).
    """
    registry = NodeRegistry()
    for nid in node_ids:
        registry.add(TraceNode(nid, action="done"))
    return registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    """Fresh SQLiteRepository per test; closed on teardown."""
    r = SQLiteRepository(tmp_path / "test.db", migrate=True)
    yield r
    r.close()


@pytest.fixture
def session(repo):
    """A read-only SessionService bound to ``run-test`` in ``conv-test``.

    The conversation and run are created before the session is reopened.
    Tests that need to insert checkpoints, events, or task states use the
    ``repo`` fixture directly (same instance — pytest resolves ``repo``
    once per test).
    """
    repo.create_conversation("conv-test")
    repo.start_run("run-test", "conv-test", "agent-1", "coordinator")
    return SessionService.reopen(
        repo,
        conversation_id="conv-test",
        run_id="run-test",
        agent_id="agent-1",
    )


# ---------------------------------------------------------------------------
# build_pending_operations
# ---------------------------------------------------------------------------


class TestBuildPendingOperations:
    """``build_pending_operations`` reconstructs the pending-operations list
    from the SessionEvent log.

    These tests construct ``SessionEvent`` dataclasses directly (no SQLite)
    so they are fast and deterministic. The function's contract is:

    - Pair events by ``operation_id``.
    - The latest ``started`` event wins (retry support).
    - The latest terminal event wins.
    - Operations with only a terminal event get a synthetic entry.
    - Events without ``operation_id`` are skipped (malformed log).
    """

    def test_empty_events_returns_empty_list(self):
        """No events → no pending operations."""
        result = build_pending_operations([])
        assert result == []

    def test_started_only_yields_started_state(self):
        """A single ``operation.started`` with no terminal event → the
        operation is in-flight (state="started")."""
        events = [
            _make_event(
                event_type="operation.started",
                operation_id="op-1",
                sequence=1,
                created_at="2026-01-01T00:00:00Z",
            ),
        ]
        result = build_pending_operations(events)
        assert len(result) == 1
        assert result[0]["operation_id"] == "op-1"
        assert result[0]["state"] == "started"
        assert result[0]["started_at"] == "2026-01-01T00:00:00Z"

    def test_started_then_committed_yields_committed_state(self):
        """``operation.started`` followed by ``operation.committed`` →
        the operation reached a terminal state (state="committed")."""
        events = [
            _make_event(
                event_type="operation.started",
                operation_id="op-1",
                sequence=1,
                created_at="2026-01-01T00:00:00Z",
            ),
            _make_event(
                event_type="operation.committed",
                operation_id="op-1",
                sequence=2,
                created_at="2026-01-01T00:01:00Z",
            ),
        ]
        result = build_pending_operations(events)
        assert len(result) == 1
        assert result[0]["operation_id"] == "op-1"
        assert result[0]["state"] == "committed"
        assert result[0]["terminal_at"] == "2026-01-01T00:01:00Z"

    def test_started_then_failed_yields_failed_state(self):
        """``operation.started`` followed by ``operation.failed`` →
        state="failed"."""
        events = [
            _make_event(
                event_type="operation.started",
                operation_id="op-1",
                sequence=1,
            ),
            _make_event(
                event_type="operation.failed",
                operation_id="op-1",
                sequence=2,
            ),
        ]
        result = build_pending_operations(events)
        assert len(result) == 1
        assert result[0]["state"] == "failed"

    def test_started_then_unknown_outcome_yields_unknown_outcome_state(self):
        """``operation.started`` followed by
        ``operation.unknown_outcome`` → state="unknown_outcome"."""
        events = [
            _make_event(
                event_type="operation.started",
                operation_id="op-1",
                sequence=1,
            ),
            _make_event(
                event_type="operation.unknown_outcome",
                operation_id="op-1",
                sequence=2,
            ),
        ]
        result = build_pending_operations(events)
        assert len(result) == 1
        assert result[0]["state"] == "unknown_outcome"

    def test_retry_multiple_started_preserves_original_started_at(self):
        """When the same operation_id has multiple ``operation.started``
        events (a retry), the LATEST started wins for state, but the
        ORIGINAL ``started_at`` is preserved so the operator can see how
        long the operation has been in flight."""
        events = [
            _make_event(
                event_type="operation.started",
                operation_id="op-1",
                sequence=1,
                created_at="2026-01-01T00:00:00Z",
            ),
            _make_event(
                event_type="operation.committed",
                operation_id="op-1",
                sequence=2,
                created_at="2026-01-01T00:01:00Z",
            ),
            # Retry: a second started event supersedes the committed state.
            _make_event(
                event_type="operation.started",
                operation_id="op-1",
                sequence=3,
                created_at="2026-01-01T00:05:00Z",
            ),
        ]
        result = build_pending_operations(events)
        assert len(result) == 1
        assert result[0]["state"] == "started"
        # started_at must be the ORIGINAL (first started), not the retry.
        assert result[0]["started_at"] == "2026-01-01T00:00:00Z"

    def test_terminal_without_started_creates_synthetic_entry(self):
        """A terminal event with no matching ``operation.started`` is
        unusual (event log truncation, partial migration) but not
        impossible. The helper records a synthetic entry with
        ``started_at=None`` so the operator can see it."""
        events = [
            _make_event(
                event_type="operation.committed",
                operation_id="op-orphan",
                sequence=1,
                created_at="2026-01-01T00:00:00Z",
            ),
        ]
        result = build_pending_operations(events)
        assert len(result) == 1
        assert result[0]["operation_id"] == "op-orphan"
        assert result[0]["state"] == "committed"
        assert result[0]["started_at"] is None
        assert result[0]["terminal_at"] == "2026-01-01T00:00:00Z"

    def test_malformed_event_missing_operation_id_is_skipped(self):
        """Events whose payload lacks a string ``operation_id`` are
        skipped — the helper cannot invent an id. Valid events in the
        same log are still processed."""
        malformed = SessionEvent(
            event_id="evt-malformed-1",
            conversation_id="conv-test",
            run_id="run-test",
            sequence=1,
            event_type="operation.started",
            payload={"schema_version": 1},  # no operation_id
            created_at=utc_now_iso(),
        )
        valid = _make_event(
            event_type="operation.started",
            operation_id="op-valid",
            sequence=2,
        )
        result = build_pending_operations([malformed, valid])
        assert len(result) == 1
        assert result[0]["operation_id"] == "op-valid"


# ---------------------------------------------------------------------------
# FileSnapshotVerifier.verify
# ---------------------------------------------------------------------------


class TestFileSnapshotVerifierVerify:
    """``FileSnapshotVerifier.verify`` returns True iff the file matches
    the snapshot's recorded state.

    These tests use real files in ``tmp_path`` (no mocking) to exercise
    the hashlib + os.path integration. Each test creates its own file to
    avoid cross-test coupling.
    """

    def test_existing_file_matches(self, tmp_path):
        """A file whose content has not changed since the snapshot was
        taken → verify returns True."""
        path = tmp_path / "file.txt"
        path.write_text("hello world", encoding="utf-8")

        verifier = FileSnapshotVerifier()
        snap = verifier.snapshot(str(path))
        assert verifier.verify(snap) is True

    def test_file_hash_mismatch_returns_false(self, tmp_path):
        """The file was modified after the snapshot was taken → the hash
        differs → verify returns False."""
        path = tmp_path / "file.txt"
        path.write_text("original content", encoding="utf-8")

        verifier = FileSnapshotVerifier()
        snap = verifier.snapshot(str(path))

        # Modify the file — the hash will differ.
        path.write_text("tampered content", encoding="utf-8")
        assert verifier.verify(snap) is False

    def test_file_missing_when_required_returns_false(self, tmp_path):
        """The snapshot recorded the file as existing
        (``existence_required=True``), but the file is now gone → verify
        returns False (state unknown)."""
        path = tmp_path / "ghost.txt"
        path.write_text("was here", encoding="utf-8")

        verifier = FileSnapshotVerifier()
        snap = verifier.snapshot(str(path))

        path.unlink()
        assert verifier.verify(snap) is False

    def test_file_missing_when_not_required_returns_true(self, tmp_path):
        """The snapshot recorded ABSENCE (``existence_required=False``)
        and the file is still absent → verify returns True. This is the
        cleanup-operation case: the snapshot asserts "this file should
        NOT exist when resume runs"."""
        path = tmp_path / "deleted.txt"

        verifier = FileSnapshotVerifier()
        snap = verifier.snapshot(str(path), existence_required=False)

        # File was never created; it is still absent.
        assert verifier.verify(snap) is True

    def test_file_exists_when_snapshot_said_absent_returns_false(self, tmp_path):
        """The snapshot recorded absence (``existence_required=False``)
        but the file now EXISTS → an external process created it →
        verify returns False (state diverged)."""
        path = tmp_path / "appeared.txt"

        verifier = FileSnapshotVerifier()
        snap = verifier.snapshot(str(path), existence_required=False)

        # An external process creates the file after the snapshot.
        path.write_text("unexpected", encoding="utf-8")
        assert verifier.verify(snap) is False


# ---------------------------------------------------------------------------
# FileSnapshotVerifier.snapshot round-trip
# ---------------------------------------------------------------------------


class TestFileSnapshotVerifierSnapshotRoundTrip:
    """Round-trip: ``snapshot`` records state, ``verify`` checks it.

    These tests confirm the two methods are complementary — a snapshot
    taken immediately before verification always matches, and any
    modification between snapshot and verify is detected.
    """

    def test_snapshot_then_verify_matches(self, tmp_path):
        """Snapshot a file, then immediately verify — the file has not
        changed, so verify returns True."""
        path = tmp_path / "round_trip.txt"
        path.write_text("stable content", encoding="utf-8")

        verifier = FileSnapshotVerifier()
        snap = verifier.snapshot(str(path))
        assert verifier.verify(snap) is True

    def test_modify_file_after_snapshot_then_verify_returns_false(
        self, tmp_path
    ):
        """Snapshot a file, modify it, then verify — the hash no longer
        matches, so verify returns False."""
        path = tmp_path / "round_trip_modify.txt"
        path.write_text("v1", encoding="utf-8")

        verifier = FileSnapshotVerifier()
        snap = verifier.snapshot(str(path))

        path.write_text("v2 — externally modified", encoding="utf-8")
        assert verifier.verify(snap) is False


# ---------------------------------------------------------------------------
# ResumeCoordinator.decide_resume — SOP §12 test matrix R-01..R-06
# ---------------------------------------------------------------------------


class TestResumeCoordinatorDecideResume:
    """End-to-end ``ResumeCoordinator.decide_resume`` tests against a
    real SQLite-backed SessionService.

    Each test sets up the repository state (checkpoint, events, task
    states) directly via ``repo`` and reads the decision via
    ``session``. The coordinator NEVER writes — it only computes the
    decision.
    """

    # ------------------------------------------------------------------
    # R-01: Step-boundary resume — clean checkpoint → ok
    # ------------------------------------------------------------------

    def test_r01_clean_checkpoint_returns_ok(self, repo, session):
        """R-01: a clean checkpoint with a matching registry, no pending
        operations, no active workers, and no file conflicts →
        ``ok`` with the correct ``next_node_id``."""
        registry = _build_registry(["next_node"])
        checkpoint = _make_checkpoint(
            last_committed_sequence=5,
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        repo.insert_checkpoint(checkpoint)

        coordinator = ResumeCoordinator(registry=registry)
        decision = coordinator.decide_resume(session)

        assert decision.status == "ok"
        assert decision.can_auto_resume is True
        assert decision.next_node_id == "next_node"
        assert decision.last_safe_sequence == 5
        assert decision.recommended_action == "resume_from_next_node"

    # ------------------------------------------------------------------
    # R-02: Pending Bash — recovery_required (NEVER auto-replay)
    # ------------------------------------------------------------------

    def test_r02_pending_bash_returns_recovery_required(self, repo, session):
        """R-02: an ``operation.started`` event for a Bash command with
        no terminal event → the operation is in-flight →
        ``recovery_required``. SOP §5.3: NEVER auto-replay a mutating
        operation."""
        registry = _build_registry(["next_node"])
        checkpoint = _make_checkpoint(
            last_committed_sequence=0,
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        repo.insert_checkpoint(checkpoint)

        # Emit a started event for a Bash operation (no terminal event).
        _emit_operation(
            repo,
            event_type="operation.started",
            operation_id="bash:cmd-1",
        )

        coordinator = ResumeCoordinator(registry=registry)
        decision = coordinator.decide_resume(session)

        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert decision.recommended_action == "initiate_recovery"
        # The pending operation is surfaced for the recovery shell.
        assert len(decision.pending_operations) == 1
        assert decision.pending_operations[0]["operation_id"] == "bash:cmd-1"

    # ------------------------------------------------------------------
    # R-03: Pending file_write — recovery_required
    # ------------------------------------------------------------------

    def test_r03_pending_file_write_returns_recovery_required(
        self, repo, session
    ):
        """R-03: an ``operation.started`` event for a file_write with no
        terminal event → the write is in-flight →
        ``recovery_required``. The coordinator treats all mutating
        operations identically regardless of kind."""
        registry = _build_registry(["next_node"])
        checkpoint = _make_checkpoint(
            last_committed_sequence=0,
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        repo.insert_checkpoint(checkpoint)

        _emit_operation(
            repo,
            event_type="operation.started",
            operation_id="file_write:/data/out.txt",
        )

        coordinator = ResumeCoordinator(registry=registry)
        decision = coordinator.decide_resume(session)

        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert len(decision.pending_operations) == 1
        assert (
            decision.pending_operations[0]["operation_id"]
            == "file_write:/data/out.txt"
        )

    # ------------------------------------------------------------------
    # R-04: External file change — recovery_required with file_conflicts
    # ------------------------------------------------------------------

    def test_r04_external_file_change_returns_recovery_required(
        self, repo, session, tmp_path
    ):
        """R-04: a file snapshot that no longer matches the filesystem
        (content was externally modified) → ``recovery_required`` with
        ``file_conflicts`` populated. This integrates
        ``FileSnapshotVerifier`` with ``ResumeCoordinator``."""
        # Create a real file and snapshot it BEFORE the checkpoint.
        file_path = tmp_path / "data.txt"
        file_path.write_text("checkpoint-time content", encoding="utf-8")

        verifier = FileSnapshotVerifier()
        snapshot = verifier.snapshot(str(file_path))

        registry = _build_registry(["next_node"])
        checkpoint = _make_checkpoint(
            last_committed_sequence=3,
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
            file_snapshots=(snapshot,),
        )
        repo.insert_checkpoint(checkpoint)

        # Externally modify the file AFTER the checkpoint was written.
        file_path.write_text("tampered content", encoding="utf-8")

        coordinator = ResumeCoordinator(
            registry=registry, file_verifier=verifier
        )
        decision = coordinator.decide_resume(session)

        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert len(decision.file_conflicts) == 1
        assert decision.file_conflicts[0]["path"] == str(file_path)

    # ------------------------------------------------------------------
    # R-05: Corrupt/missing checkpoint — recovery_required
    # ------------------------------------------------------------------

    def test_no_checkpoint_returns_recovery_required(self, session):
        """No Checkpoint exists for the run →
        ``recovery_required`` with a reason mentioning "no Checkpoint
        exists". Resume cannot proceed without a safe step boundary.

        Note: SOP §12 R-05 defines "Corrupt checkpoint — state_hash
        failure". That state_hash recomputation case is deferred to
        v0.04.1 (E-DEBT-4 in resume_boundary.json) because it requires
        a state-hash recomputation helper that knows the original state
        at checkpoint time. This test covers the related but distinct
        case "no Checkpoint exists at all", which is SOP §10.1
        condition 1 failure."""
        registry = _build_registry(["next_node"])

        coordinator = ResumeCoordinator(registry=registry)
        decision = coordinator.decide_resume(session)

        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert "no Checkpoint exists" in decision.reason
        assert decision.recommended_action == "initiate_recovery"
        assert decision.last_safe_sequence == 0

    # ------------------------------------------------------------------
    # R-06: Active Worker marker — recovery_required (detect only)
    # ------------------------------------------------------------------

    def test_r06_active_worker_returns_recovery_required(self, repo, session):
        """R-06: a TaskState with status="active" means a Worker may
        still be in flight → ``recovery_required``. v0.04 only DETECTS
        this condition; it does not attempt to recover the Worker
        (SOP §10.3 explicit non-goal)."""
        registry = _build_registry(["next_node"])
        checkpoint = _make_checkpoint(
            last_committed_sequence=2,
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        repo.insert_checkpoint(checkpoint)

        # Mark a Worker as still active.
        repo.upsert_task_state(
            "worker-1",
            "run-test",
            "active",
            {"worker_id": "worker-1", "schema_version": 1},
        )

        coordinator = ResumeCoordinator(registry=registry)
        decision = coordinator.decide_resume(session)

        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert "active" in decision.reason.lower()
        assert decision.recommended_action == "initiate_recovery"

    # ------------------------------------------------------------------
    # Schema version gate
    # ------------------------------------------------------------------

    def test_unsupported_schema_version_returns_recovery_required(
        self, repo, session
    ):
        """A Checkpoint with ``schema_version=99`` is not in the
        supported set ``{1}`` → ``recovery_required``. The coordinator
        does not know how to read a future schema; a migration step is
        required before resume."""
        registry = _build_registry(["next_node"])
        checkpoint = _make_checkpoint(
            last_committed_sequence=1,
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
            schema_version=99,
        )
        repo.insert_checkpoint(checkpoint)

        coordinator = ResumeCoordinator(registry=registry)
        decision = coordinator.decide_resume(session)

        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert "schema_version" in decision.reason
        assert "99" in decision.reason

    # ------------------------------------------------------------------
    # Pre-computed pending_operations (skip event-log reconstruction)
    # ------------------------------------------------------------------

    def test_pre_computed_pending_operations_skips_event_log(
        self, repo, session
    ):
        """When the caller passes ``pending_operations`` explicitly, the
        coordinator uses that list instead of reconstructing from the
        event log. This test proves the skip: events that WOULD produce
        a pending operation are ignored when an empty list is passed."""
        registry = _build_registry(["next_node"])
        checkpoint = _make_checkpoint(
            last_committed_sequence=0,
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        repo.insert_checkpoint(checkpoint)

        # Emit a started event — if the coordinator reconstructed from
        # the log, this would block resume. But we pass an explicit
        # empty list, so the coordinator skips reconstruction.
        _emit_operation(
            repo,
            event_type="operation.started",
            operation_id="op-ignored",
        )

        coordinator = ResumeCoordinator(registry=registry)
        decision = coordinator.decide_resume(
            session, pending_operations=[]
        )

        assert decision.status == "ok"
        assert decision.can_auto_resume is True
        assert decision.next_node_id == "next_node"

    def test_pre_computed_pending_operations_with_started_blocks_resume(
        self, repo, session
    ):
        """Passing a non-empty ``pending_operations`` list with a
        started operation → ``recovery_required``. This confirms the
        coordinator honors the passed-in list (not just ignoring it)."""
        registry = _build_registry(["next_node"])
        checkpoint = _make_checkpoint(
            last_committed_sequence=1,
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        repo.insert_checkpoint(checkpoint)

        coordinator = ResumeCoordinator(registry=registry)
        decision = coordinator.decide_resume(
            session,
            pending_operations=[
                {"operation_id": "op-injected", "state": "started"}
            ],
        )

        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert len(decision.pending_operations) == 1
        assert decision.pending_operations[0]["operation_id"] == "op-injected"
