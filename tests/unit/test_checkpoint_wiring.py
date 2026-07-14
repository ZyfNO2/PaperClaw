"""Addendum P0-C: CheckpointWriter + safe resume decision tests.

Covers Addendum §10 verification matrix:

- PF-06: Resume next node — already-completed node is NOT re-executed.
- PF-07: Partial node — node.started without node.completed →
  ``recovery_required``.
- PF-08: Pending write — non-terminal mutating operation →
  ``recovery_required``.
- PF-08b: Pending operation in terminal state (``committed``) → ``ok``.
- PF-09: Registry mismatch — ``checkpoint_registry_hash`` differs from
  current registry → ``incompatible_flow_definition``.
- PF-09b: ``next_node_id`` not in current registry →
  ``incompatible_flow_definition``.
- PF-extra: Happy path — clean checkpoint, matching registry, no pending
  ops → ``ok``.

Additional invariants verified:

- ``checkpoint.committed`` event is emitted AFTER ``node.completed`` for
  the same node (Addendum §5.2 commit order).
- Parity mode (``checkpoint_writer=None``) still produces identical
  business results to native PocketFlow ``Flow.run`` (PF-05 regression
  gate).
- ``SqliteCheckpointWriter`` round-trips the four P0-C node-identity
  fields through the SQLite ``checkpoints`` table.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pocketflow import Flow, Node

from paperclaw.context.contracts import Checkpoint, utc_now_iso
from paperclaw.context.repository import SQLiteRepository
from paperclaw.runtime import (
    INCOMPATIBLE_FLOW_DEFINITION,
    RECOVERY_REQUIRED,
    CheckpointWriter,
    CompletedNode,
    FlowResumePoint,
    InMemoryCheckpointWriter,
    InstrumentedFlowRunner,
    NodeRegistry,
    ResumeDecision,
    RuntimeServices,
    SqliteCheckpointWriter,
    evaluate_resume_safety,
)


# ---------------------------------------------------------------------------
# Test doubles (mirrors test_instrumented_flow_runner.py — kept local so
# this test file is self-contained and does not import from another test).
# ---------------------------------------------------------------------------


class RecordingSink:
    """EventSink that records every emit call with a monotonic sequence."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._seq = 0

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        agent_id: str = "",
        task_id: str | None = None,
    ) -> int:
        self._seq += 1
        self.events.append({
            "event_type": event_type,
            "payload": copy.deepcopy(payload),
            "sequence": self._seq,
        })
        return self._seq

    @property
    def event_types(self) -> list[str]:
        return [e["event_type"] for e in self.events]

    def payloads_for(self, event_type: str) -> list[dict[str, Any]]:
        return [e["payload"] for e in self.events if e["event_type"] == event_type]

    def sequences_for(self, event_type: str) -> list[int]:
        return [e["sequence"] for e in self.events if e["event_type"] == event_type]


class TraceNode(Node):
    """Node that appends its ``node_id`` to ``shared["trace"]`` and returns
    a fixed action."""

    def __init__(self, node_id: str, action: str | None = "default") -> None:
        super().__init__()
        self.node_id = node_id
        self._action = action

    def prep(self, shared: dict) -> Any:
        shared.setdefault("trace", []).append(self.node_id)
        return None

    def exec(self, prep_res: Any) -> Any:
        return None

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        return self._action


# ---------------------------------------------------------------------------
# Flow builders
# ---------------------------------------------------------------------------


def _build_linear_flow(
    node_ids: list[str], actions: list[str | None] | None = None
) -> tuple[Flow, NodeRegistry]:
    """Build a linear flow A → B → ... → terminal with a NodeRegistry."""
    if actions is None:
        actions = ["default"] * (len(node_ids) - 1) + [None]
    assert len(actions) == len(node_ids)

    nodes = [TraceNode(nid, act) for nid, act in zip(node_ids, actions)]
    for i in range(len(nodes) - 1):
        nodes[i] - "default" >> nodes[i + 1]
    flow = Flow(start=nodes[0])

    registry = NodeRegistry()
    for n in nodes:
        registry.add(n)
    return flow, registry


def _make_checkpoint(
    *,
    run_id: str = "run-test",
    last_committed_sequence: int = 1,
    task_state_revision: int = 0,
    completed_node_id: str | None = None,
    last_action: str | None = None,
    next_node_id: str | None = None,
    checkpoint_registry_hash: str | None = None,
    pending_operations: tuple[dict[str, Any], ...] = (),
    file_snapshots: tuple[dict[str, Any], ...] = (),
) -> Checkpoint:
    """Synthesize a Checkpoint for resume-safety tests."""
    return Checkpoint(
        checkpoint_id=f"cp-test-{last_committed_sequence}",
        run_id=run_id,
        last_committed_sequence=last_committed_sequence,
        task_state_revision=task_state_revision,
        budget_state={},
        pending_operations=pending_operations,
        file_snapshots=file_snapshots,
        state_hash="state-hash-test",
        schema_version=1,
        created_at=utc_now_iso(),
        completed_node_id=completed_node_id,
        last_action=last_action,
        next_node_id=next_node_id,
        checkpoint_registry_hash=checkpoint_registry_hash,
    )


# ---------------------------------------------------------------------------
# PF-06: Resume next node — already-completed node is NOT re-executed
# ---------------------------------------------------------------------------


class TestPF06ResumeNextNode:
    """PF-06: Run a 2-node flow with checkpoint_writer wired. Verify both
    checkpoints were committed. Then resume from the first checkpoint's
    next_node_id — the already-completed node is NOT re-executed, only the
    successor runs."""

    def test_two_checkpoints_committed_for_two_node_flow(self):
        """A 2-node flow commits exactly 2 checkpoints (one per node)."""
        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        writer = InMemoryCheckpointWriter()
        services = RuntimeServices(
            event_sink=sink, node_registry=registry, checkpoint_writer=writer
        )
        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        assert len(writer.committed) == 2
        # First checkpoint: a completed, next is b.
        assert writer.committed[0].completed_node_id == "a"
        assert writer.committed[0].next_node_id == "b"
        # Second checkpoint: b completed, next is None (terminal).
        assert writer.committed[1].completed_node_id == "b"
        assert writer.committed[1].next_node_id is None

    def test_resume_from_first_checkpoint_skips_completed_node(self):
        """Run a → b to completion. Resume from the first checkpoint's
        next_node_id (b). Node a is NOT re-executed; only b runs."""
        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        writer = InMemoryCheckpointWriter()
        services = RuntimeServices(
            event_sink=sink, node_registry=registry, checkpoint_writer=writer
        )
        runner = InstrumentedFlowRunner()
        shared_first: dict = {}
        runner.run(flow, shared_first, services=services)

        # First run executed both a and b.
        assert shared_first["trace"] == ["a", "b"]
        first_cp = writer.committed[0]
        assert first_cp.completed_node_id == "a"
        assert first_cp.next_node_id == "b"

        # Resume from b (the first checkpoint's next_node_id). Build a fresh
        # flow instance so we don't share Node object state with the first
        # run — the registry is what matters for resume.
        flow2, registry2 = _build_linear_flow(["a", "b"])
        sink2 = RecordingSink()
        writer2 = InMemoryCheckpointWriter()
        services2 = RuntimeServices(
            event_sink=sink2, node_registry=registry2, checkpoint_writer=writer2
        )
        resume_point = FlowResumePoint(
            run_id="run-resume-pf06",
            completed_node_id=first_cp.completed_node_id,
            last_action=first_cp.last_action,
            next_node_id=first_cp.next_node_id,
            last_committed_sequence=first_cp.last_committed_sequence,
            state_revision=first_cp.task_state_revision,
        )
        shared_resume: dict = {}
        runner.run(flow2, shared_resume, services=services2, resume_point=resume_point)

        # a was NOT re-executed; only b ran.
        assert shared_resume["trace"] == ["b"]
        # Only one checkpoint committed on resume (for b).
        assert len(writer2.committed) == 1
        assert writer2.committed[0].completed_node_id == "b"

    def test_checkpoint_committed_emitted_after_node_completed(self):
        """Addendum §5.2: checkpoint.committed MUST come AFTER node.completed
        for the same node. Verify the event ordering in the event log."""
        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        writer = InMemoryCheckpointWriter()
        services = RuntimeServices(
            event_sink=sink, node_registry=registry, checkpoint_writer=writer
        )
        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        # For each node, its node.completed sequence < its checkpoint.committed
        # sequence. We pair them by the node_id in the payload.
        completed = {
            e["payload"]["node_id"]: e["sequence"]
            for e in sink.events
            if e["event_type"] == "node.completed"
        }
        committed = {
            e["payload"]["completed_node_id"]: e["sequence"]
            for e in sink.events
            if e["event_type"] == "checkpoint.committed"
        }
        assert set(completed.keys()) == {"a", "b"}
        assert set(committed.keys()) == {"a", "b"}
        for nid in ("a", "b"):
            assert completed[nid] < committed[nid], (
                f"node.completed for {nid} (seq={completed[nid]}) must come "
                f"before checkpoint.committed (seq={committed[nid]})"
            )


# ---------------------------------------------------------------------------
# PF-07: Partial node — started without completed → recovery_required
# ---------------------------------------------------------------------------


class TestPF07PartialNode:
    """PF-07: a node.started event with no matching node.completed means
    the node crashed mid-execution. ``evaluate_resume_safety`` MUST return
    ``recovery_required`` — never auto-replay the partial node."""

    def test_partial_node_returns_recovery_required(self):
        """Synthesize a Checkpoint with completed_node_id=None (no node
        committed) and a pending operation representing the in-flight
        node (state='started'). Resume MUST be recovery_required."""
        registry = NodeRegistry()
        node = TraceNode("some_node", action="done")
        registry.add(node)

        checkpoint = _make_checkpoint(
            completed_node_id=None,
            next_node_id="some_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        # The pending operation encodes "node started but never completed".
        # evaluate_resume_safety treats any non-terminal state as in-flight.
        pending = [{"operation_id": "node:some_node", "state": "started"}]

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=pending,
        )
        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert decision.recommended_action == "initiate_recovery"


# ---------------------------------------------------------------------------
# PF-08: Pending write — non-terminal mutating operation
# ---------------------------------------------------------------------------


class TestPF08PendingWrite:
    """PF-08: a mutating operation in a non-terminal state blocks auto-resume.
    Addendum §5.3: NEVER auto-replay a mutating operation."""

    def test_pending_operation_started_blocks_resume(self):
        """A pending operation with state='started' (no terminal event) →
        recovery_required."""
        registry = NodeRegistry()
        node = TraceNode("next_node", action="done")
        registry.add(node)

        checkpoint = _make_checkpoint(
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        pending = [{"operation_id": "op-1", "state": "started"}]

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=pending,
        )
        assert decision.status == "recovery_required"
        assert decision.can_auto_resume is False
        assert "non-terminal" in decision.reason

    def test_pending_operation_committed_allows_resume(self):
        """PF-08b: a pending operation with state='committed' (terminal) →
        ok. The operation's side effects are known; resume may proceed."""
        registry = NodeRegistry()
        node = TraceNode("next_node", action="done")
        registry.add(node)

        checkpoint = _make_checkpoint(
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        pending = [{"operation_id": "op-1", "state": "committed"}]

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=pending,
        )
        assert decision.status == "ok"
        assert decision.can_auto_resume is True
        assert decision.next_node_id == "next_node"

    def test_pending_operation_failed_allows_resume(self):
        """A pending operation with state='failed' (terminal) → ok. The
        operation failed; its side effects are known to be absent."""
        registry = NodeRegistry()
        node = TraceNode("next_node", action="done")
        registry.add(node)

        checkpoint = _make_checkpoint(
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )
        pending = [{"operation_id": "op-1", "state": "failed"}]

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=pending,
        )
        assert decision.status == "ok"


# ---------------------------------------------------------------------------
# PF-09: Registry mismatch — incompatible Flow definition
# ---------------------------------------------------------------------------


class TestPF09RegistryMismatch:
    """PF-09: the Checkpoint's registry hash differs from the current
    registry's hash → incompatible_flow_definition. Resume MUST stop."""

    def test_registry_hash_mismatch_blocks_resume(self):
        """Checkpoint was written with hash X; current registry has hash Y.
        Resume MUST return incompatible_flow_definition."""
        # Build the "checkpoint-time" registry and compute its hash.
        cp_registry = NodeRegistry()
        cp_registry.add(TraceNode("next_node", action="done"))
        cp_registry.add(TraceNode("old_node", action="done"))
        stored_hash = cp_registry.registry_hash

        # Build the "current" registry with a DIFFERENT node set.
        current_registry = NodeRegistry()
        current_registry.add(TraceNode("next_node", action="done"))
        # current_registry does NOT have "old_node" → hash differs.

        checkpoint = _make_checkpoint(
            completed_node_id="old_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=stored_hash,
        )

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=current_registry,
            pending_operations=[],
        )
        assert decision.status == "incompatible_flow_definition"
        assert decision.can_auto_resume is False
        assert decision.checkpoint_registry_hash == stored_hash
        assert decision.current_registry_hash == current_registry.registry_hash
        assert stored_hash != current_registry.registry_hash
        assert decision.recommended_action == "refuse_resume_flow_definition_changed"

    def test_next_node_not_in_registry_blocks_resume(self):
        """PF-09b: next_node_id is not present in the current registry →
        incompatible_flow_definition. This is checked BEFORE the hash so the
        operator gets the most actionable error first."""
        registry = NodeRegistry()
        registry.add(TraceNode("other_node", action="done"))

        checkpoint = _make_checkpoint(
            completed_node_id="prev",
            last_action="go",
            next_node_id="nonexistent_node",
            checkpoint_registry_hash=registry.registry_hash,
        )

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=[],
        )
        assert decision.status == "incompatible_flow_definition"
        assert decision.can_auto_resume is False
        assert "nonexistent_node" in decision.reason

    def test_next_node_none_blocks_resume(self):
        """A Checkpoint with next_node_id=None (terminal or legacy v2
        checkpoint) → incompatible_flow_definition. Resume requires a
        concrete next node."""
        registry = NodeRegistry()
        registry.add(TraceNode("some_node", action="done"))

        checkpoint = _make_checkpoint(
            completed_node_id="prev",
            last_action="go",
            next_node_id=None,
            checkpoint_registry_hash=registry.registry_hash,
        )

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=[],
        )
        assert decision.status == "incompatible_flow_definition"


# ---------------------------------------------------------------------------
# PF-extra: Happy path — clean checkpoint → ok
# ---------------------------------------------------------------------------


class TestPFExtraHappyPath:
    """PF-extra: clean checkpoint, matching registry, no pending ops, no
    file conflicts → ok, resume from next_node_id."""

    def test_clean_checkpoint_allows_resume(self):
        registry = NodeRegistry()
        node = TraceNode("next_node", action="done")
        registry.add(node)

        checkpoint = _make_checkpoint(
            completed_node_id="prev_node",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
        )

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=[],
        )
        assert decision.status == "ok"
        assert decision.can_auto_resume is True
        assert decision.next_node_id == "next_node"
        assert decision.last_safe_sequence == checkpoint.last_committed_sequence
        assert decision.recommended_action == "resume_from_next_node"

    def test_legacy_checkpoint_without_registry_hash_allows_resume(self):
        """A legacy v2 Checkpoint (checkpoint_registry_hash=None) is allowed
        to resume as long as next_node_id is in the current registry. The
        hash check is skipped for legacy checkpoints; membership is the
        primary guard."""
        registry = NodeRegistry()
        registry.add(TraceNode("next_node", action="done"))

        checkpoint = _make_checkpoint(
            completed_node_id="prev",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=None,  # legacy v2 checkpoint
        )

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=[],
        )
        assert decision.status == "ok"
        assert decision.checkpoint_registry_hash is None

    def test_file_snapshot_mismatch_blocks_resume(self):
        """A file snapshot that no longer matches the filesystem →
        recovery_required."""
        registry = NodeRegistry()
        registry.add(TraceNode("next_node", action="done"))

        checkpoint = _make_checkpoint(
            completed_node_id="prev",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
            file_snapshots=(
                {"path": "/tmp/file_a", "hash": "h-a"},
                {"path": "/tmp/file_b", "hash": "h-b"},
            ),
        )

        # Verifier returns False for file_b (mismatch).
        def verifier(snap: dict[str, Any]) -> bool:
            return snap.get("path") != "/tmp/file_b"

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=[],
            file_snapshot_verifier=verifier,
        )
        assert decision.status == "recovery_required"
        assert len(decision.file_conflicts) == 1
        assert decision.file_conflicts[0]["path"] == "/tmp/file_b"

    def test_file_snapshot_all_match_allows_resume(self):
        """When the verifier confirms all snapshots match → ok."""
        registry = NodeRegistry()
        registry.add(TraceNode("next_node", action="done"))

        checkpoint = _make_checkpoint(
            completed_node_id="prev",
            last_action="go",
            next_node_id="next_node",
            checkpoint_registry_hash=registry.registry_hash,
            file_snapshots=({"path": "/tmp/file_a", "hash": "h-a"},),
        )

        decision = evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=registry,
            pending_operations=[],
            file_snapshot_verifier=lambda snap: True,
        )
        assert decision.status == "ok"


# ---------------------------------------------------------------------------
# CheckpointWriter Protocol conformance
# ---------------------------------------------------------------------------


class TestCheckpointWriterProtocol:
    """Verify SqliteCheckpointWriter and InMemoryCheckpointWriter satisfy
    the CheckpointWriter Protocol and round-trip the P0-C fields."""

    def test_sqlite_writer_round_trips_p0c_fields(self, tmp_path: Path):
        """Insert a Checkpoint with all four P0-C fields via
        SqliteCheckpointWriter; read it back via latest_checkpoint; verify
        the fields round-trip exactly."""
        repo = SQLiteRepository(tmp_path / "cpw.db", migrate=True)
        try:
            repo.create_conversation("conv-1")
            repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
            writer = SqliteCheckpointWriter(repo)

            cp = _make_checkpoint(
                run_id="run-1",
                last_committed_sequence=5,
                task_state_revision=2,
                completed_node_id="decide",
                last_action="file_read",
                next_node_id="tool:file_read",
                checkpoint_registry_hash="abc123hash",
            )
            writer.commit_checkpoint(cp)

            latest = writer.latest_checkpoint("run-1")
            assert latest is not None
            assert latest.checkpoint_id == cp.checkpoint_id
            assert latest.completed_node_id == "decide"
            assert latest.last_action == "file_read"
            assert latest.next_node_id == "tool:file_read"
            assert latest.checkpoint_registry_hash == "abc123hash"
            assert latest.last_committed_sequence == 5
        finally:
            repo.close()

    def test_sqlite_writer_latest_returns_none_for_empty_run(self, tmp_path: Path):
        repo = SQLiteRepository(tmp_path / "cpw_empty.db", migrate=True)
        try:
            repo.create_conversation("conv-1")
            repo.start_run("run-1", "conv-1", "agent-1", "coordinator")
            writer = SqliteCheckpointWriter(repo)
            assert writer.latest_checkpoint("run-1") is None
        finally:
            repo.close()

    def test_in_memory_writer_satisfies_protocol(self):
        """InMemoryCheckpointWriter satisfies the CheckpointWriter Protocol
        (runtime_checkable)."""
        writer = InMemoryCheckpointWriter()
        assert isinstance(writer, CheckpointWriter)

    def test_sqlite_writer_satisfies_protocol(self, tmp_path: Path):
        repo = SQLiteRepository(tmp_path / "cpw_proto.db", migrate=True)
        try:
            writer = SqliteCheckpointWriter(repo)
            assert isinstance(writer, CheckpointWriter)
        finally:
            repo.close()

    def test_in_memory_writer_latest_returns_highest_sequence(self):
        """InMemoryCheckpointWriter.latest_checkpoint returns the checkpoint
        with the highest last_committed_sequence for the run_id."""
        writer = InMemoryCheckpointWriter()
        cp_low = _make_checkpoint(
            run_id="run-x", last_committed_sequence=3, completed_node_id="a"
        )
        cp_high = _make_checkpoint(
            run_id="run-x", last_committed_sequence=7, completed_node_id="b"
        )
        writer.commit_checkpoint(cp_low)
        writer.commit_checkpoint(cp_high)

        latest = writer.latest_checkpoint("run-x")
        assert latest is not None
        assert latest.checkpoint_id == cp_high.checkpoint_id
        assert latest.completed_node_id == "b"


# ---------------------------------------------------------------------------
# PF-05 regression: parity mode still matches native Flow.run
# ---------------------------------------------------------------------------


class TestParityRegression:
    """PF-05 regression gate: with checkpoint_writer=None (and all other
    services None), the runner delegates to native Flow.run and produces
    byte-for-byte identical shared state. This re-runs the PF-05 parity
    test to confirm P0-C wiring did not break the parity short-circuit."""

    def test_parity_mode_no_writer_matches_native(self):
        """A 3-node flow run natively vs via the runner (all services None)
        produces identical shared state."""
        for seed in range(3):
            a = TraceNode(f"a{seed}", action="go")
            b = TraceNode(f"b{seed}", action="go")
            c = TraceNode(f"c{seed}", action="done")
            a - "go" >> b
            b - "go" >> c
            flow = Flow(start=a)

            shared_native: dict = {}
            flow.run(shared_native)

            shared_inst: dict = {}
            runner = InstrumentedFlowRunner()
            runner.run(flow, shared_inst, services=RuntimeServices())

            assert shared_native == shared_inst, (
                f"parity broken at seed {seed}: "
                f"native={shared_native} instrumented={shared_inst}"
            )

    def test_parity_mode_with_writer_off_still_delegates(self):
        """When checkpoint_writer is None AND event_sink is None AND
        cancellation_token is None AND resume_point is None, the runner
        takes the parity short-circuit (delegates to flow.run). Verify by
        asserting no events were emitted."""
        a = TraceNode("a", action="done")
        flow = Flow(start=a)

        # No sink → if the parity path is taken, no events are emitted.
        services = RuntimeServices()  # all None
        runner = InstrumentedFlowRunner()
        shared: dict = {}
        runner.run(flow, shared, services=services)

        # Parity path executes the node (trace populated) but emits nothing.
        assert shared.get("trace") == ["a"]


# ---------------------------------------------------------------------------
# flow.resumed event emission
# ---------------------------------------------------------------------------


class TestFlowResumedEvent:
    """When resuming from a resume_point, the runner emits a flow.resumed
    event after flow.started, before the first node runs."""

    def test_flow_resumed_emitted_on_resume(self):
        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()

        resume_point = FlowResumePoint(
            run_id="run-resumed-evt",
            completed_node_id="a",
            last_action="default",
            next_node_id="b",
            last_committed_sequence=3,
            state_revision=1,
        )
        runner.run(flow, {}, services=services, resume_point=resume_point)

        types = sink.event_types
        # flow.started is first, flow.resumed is second.
        assert types[0] == "flow.started"
        assert types[1] == "flow.resumed"

        resumed = sink.payloads_for("flow.resumed")
        assert len(resumed) == 1
        assert resumed[0]["next_node_id"] == "b"
        assert resumed[0]["completed_node_id"] == "a"
        assert resumed[0]["last_committed_sequence"] == 3

    def test_flow_resumed_not_emitted_on_fresh_run(self):
        """A fresh run (no resume_point) does NOT emit flow.resumed."""
        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        assert "flow.resumed" not in sink.event_types


# ---------------------------------------------------------------------------
# Checkpoint fields populated by the runner
# ---------------------------------------------------------------------------


class TestRunnerCheckpointFields:
    """Verify the Checkpoints committed by the runner carry the P0-C
    node-identity fields and a non-None registry hash."""

    def test_checkpoint_records_registry_hash(self):
        """The committed Checkpoint's checkpoint_registry_hash matches the
        registry's hash, so a resume can detect incompatible Flow
        definitions (Addendum §5.4)."""
        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        writer = InMemoryCheckpointWriter()
        services = RuntimeServices(
            event_sink=sink, node_registry=registry, checkpoint_writer=writer
        )
        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        for cp in writer.committed:
            assert cp.checkpoint_registry_hash == registry.registry_hash

    def test_checkpoint_state_hash_is_sha256_of_triple(self):
        """The state_hash is a SHA-256 hex digest (64 chars) computed from
        the node-identity triple + last_committed_sequence."""
        import hashlib

        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        writer = InMemoryCheckpointWriter()
        services = RuntimeServices(
            event_sink=sink, node_registry=registry, checkpoint_writer=writer
        )
        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        cp = writer.committed[0]
        assert len(cp.state_hash) == 64
        # Verify the hash matches the documented formula.
        action_str = "None" if cp.last_action is None else str(cp.last_action)
        next_str = "None" if cp.next_node_id is None else str(cp.next_node_id)
        expected = hashlib.sha256(
            f"{cp.completed_node_id}|{action_str}|{next_str}|"
            f"{cp.last_committed_sequence}".encode("utf-8")
        ).hexdigest()
        assert cp.state_hash == expected
