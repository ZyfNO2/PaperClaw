"""PaperClaw v0.04 MVP 端到端集成演示.

Demonstrates the SOP §9 minimal flow in a single pytest run:

  1. Long task → Context exceeds budget
  2. Deterministic compaction runs
  3. Required constraints + Evidence refs retained 100%
  4. Snapshot + Checkpoint persisted
  5. Session closed + reopened
  6. Safe resume decision = ok (file consistent, no pending mutation)
  7. Pending mutation injected → recovery_required

The test writes a trace JSON to ``artifacts/v0_04/mvp_demo_trace.json``
so the demo can be replayed / inspected without re-running pytest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pocketflow import Node

from paperclaw.context import (
    Checkpoint,
    CompactionPolicy,
    ContextBudget,
    ContextBuilder,
    ContextItem,
    ContextSource,
    RoleContextView,
    SQLiteRepository,
    SessionService,
)
from paperclaw.context.contracts import SCOPE_SHARED, utc_now_iso
from paperclaw.runtime import (
    FileSnapshotVerifier,
    NodeRegistry,
    ResumeCoordinator,
)

#: Where the replayable trace JSON is written. This is a fixed project
#: artifact path (NOT tmp_path) so reviewers can find the trace without
#: re-running the test.
ARTIFACT_DIR = Path(__file__).parent.parent.parent / "artifacts" / "v0_04"


# ---------------------------------------------------------------------------
# Test double: minimal PocketFlow Node with stable node_id
# ---------------------------------------------------------------------------


class _TraceNode(Node):
    """PocketFlow Node carrying a stable ``node_id`` for the registry.

    The NodeRegistry requires nodes to expose a ``node_id`` attribute so
    Checkpoints can record which node to resume from. The actual
    ``prep`` / ``exec`` / ``post`` logic is irrelevant for this demo —
    the ResumeCoordinator never enters a node, it only reads registry
    membership and hash.
    """

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id

    def prep(self, shared: dict) -> Any:
        return None

    def exec(self, prep_res: Any) -> Any:
        return None

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        return "done"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def trace() -> dict[str, Any]:
    """Collect evidence at each stage for the trace JSON."""
    return {"stages": []}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(sequence: int, ref: str | None = None) -> ContextSource:
    """Build a system-trust ContextSource for seeded items."""
    return ContextSource(
        source_type="runtime",
        source_ref=ref or f"ref-{sequence}",
        trust_level="system",
        created_sequence=sequence,
    )


def _make_item(
    *,
    item_id: str,
    run_id: str,
    kind: str,
    content: str,
    tokens: int,
    priority: int = 50,
    layer: str = "L3",
    valid_from: int = 0,
) -> ContextItem:
    """Construct a ContextItem with shared scope and system trust."""
    return ContextItem(
        item_id=item_id,
        run_id=run_id,
        layer=layer,
        kind=kind,
        content=content,
        source=_make_source(valid_from, ref=f"seed-{item_id}"),
        priority=priority,
        scope=(SCOPE_SHARED,),
        estimated_tokens=tokens,
        valid_from_sequence=valid_from,
    )


# ---------------------------------------------------------------------------
# The demo test
# ---------------------------------------------------------------------------


def test_v0_04_mvp_demo(trace: dict[str, Any], tmp_path: Path) -> None:
    """Single end-to-end MVP demo covering SOP §9 five stages.

    Stage 1 — Setup: fresh database, seed a long task context.
    Stage 2 — Budget overflow + deterministic compaction.
    Stage 3 — Checkpoint + close session.
    Stage 4 — Reopen + safe resume decision = ok.
    Stage 5 — Inject pending mutation → recovery_required.
    """
    db_path = tmp_path / "demo.db"
    conv_id = "conv-demo"
    run_id = "run-demo"
    agent_id = "agent-demo"

    repo = SQLiteRepository(db_path, migrate=True)
    try:
        # ===== Stage 1: Setup — seed long task context =====
        repo.create_conversation(conv_id)
        repo.start_run(run_id, conv_id, agent_id, "coordinator")

        # Seed a required constraint (protected — never evicted).
        constraint_item = _make_item(
            item_id="constraint-1",
            run_id=run_id,
            kind="constraint",
            content="do not bypass verify gate",
            tokens=50,
            priority=90,
            layer="L3",
        )
        # Seed an evidence_ref (protected — never evicted).
        evidence_item = _make_item(
            item_id="evidence-1",
            run_id=run_id,
            kind="evidence_ref",
            content="doi:10.1000/abc123",
            tokens=10,
            priority=80,
            layer="L3",
        )
        # Seed 10 observation items with large token estimates so the
        # total far exceeds the small budget. Each observation carries
        # 260 tokens — more than the remaining budget after protected
        # items — so ALL observations are evicted in first-pass
        # selection and subsequently compacted into a summary.
        observation_items = [
            _make_item(
                item_id=f"obs-{i}",
                run_id=run_id,
                kind="observation",
                content=f"observation payload number {i} - filler text for demo",
                tokens=260,
                priority=10,
                layer="L4",
            )
            for i in range(1, 11)
        ]
        for item in [constraint_item, evidence_item, *observation_items]:
            repo.insert_context_item(item)

        seeded_ids = ["constraint-1", "evidence-1"] + [
            f"obs-{i}" for i in range(1, 11)
        ]

        trace["stages"].append(
            {
                "stage": "1_setup",
                "db_path": str(db_path),
                "conversation_id": conv_id,
                "run_id": run_id,
                "items_seeded": seeded_ids,
                "total_seeded_tokens": 50 + 10 + 260 * 10,
            }
        )

        # ===== Stage 2: Budget overflow + deterministic compaction =====
        # Budget: usable_input = 400 - 50 - 40 = 310.
        # Protected items = 50 + 10 = 60. Each observation = 260 > 250
        # (remaining after protected), so all observations are evicted.
        # Compaction merges 10 observations into 1 summary (~125 tokens).
        # Post-compaction total = 60 + 125 = 185 <= 310. ✓
        small_budget = ContextBudget(
            max_input_tokens=400,
            reserved_output_tokens=50,
            safety_margin_tokens=40,
            max_single_item_tokens=300,
            max_tool_output_tokens=200,
        )
        builder = ContextBuilder(repo, compaction_policy=CompactionPolicy())
        view = RoleContextView(role="coordinator")
        snapshot = builder.build(
            run_id=run_id,
            view=view,
            budget=small_budget,
            agent_id=agent_id,
            at_sequence=1,
        )

        # Assert: snapshot fits within usable_input after compaction.
        assert snapshot.estimated_tokens <= small_budget.usable_input(), (
            f"snapshot tokens {snapshot.estimated_tokens} exceed "
            f"usable_input {small_budget.usable_input()}"
        )
        # Assert: required constraint retained.
        assert "constraint-1" in snapshot.source_item_ids, (
            "required constraint was dropped during compaction"
        )
        # Assert: evidence_ref retained.
        assert "evidence-1" in snapshot.source_item_ids, (
            "evidence_ref was dropped during compaction"
        )
        # Assert: original observation IDs are NOT in the snapshot
        # (they were absorbed into a compaction summary).
        for i in range(1, 11):
            assert f"obs-{i}" not in snapshot.source_item_ids, (
                f"obs-{i} should have been compacted into a summary"
            )
        # Assert: at least one budget_overflow exclusion recorded.
        budget_exclusions = [
            ex
            for ex in snapshot.excluded_items
            if ex.get("exclusion_reason") == "budget_overflow"
        ]
        assert len(budget_exclusions) >= 1, "expected budget_overflow exclusions"

        trace["stages"].append(
            {
                "stage": "2_compaction",
                "snapshot_id": snapshot.snapshot_id,
                "estimated_tokens": snapshot.estimated_tokens,
                "usable_input": small_budget.usable_input(),
                "source_item_ids": list(snapshot.source_item_ids),
                "excluded_count": len(snapshot.excluded_items),
                "budget_overflow_count": len(budget_exclusions),
                "rendered_hash": snapshot.rendered_hash,
            }
        )

        # ===== Stage 3: Checkpoint + close session =====
        registry = NodeRegistry()
        registry.add(_TraceNode("node-A"))

        checkpoint = Checkpoint(
            checkpoint_id="cp-demo-1",
            run_id=run_id,
            last_committed_sequence=1,
            task_state_revision=0,
            budget_state={},
            pending_operations=(),
            file_snapshots=(),
            state_hash="demo-state-hash",
            schema_version=1,
            created_at=utc_now_iso(),
            completed_node_id="node-A",
            last_action="executed",
            next_node_id="node-A",
            checkpoint_registry_hash=registry.registry_hash,
        )
        repo.insert_checkpoint(checkpoint)

        session = SessionService(
            repo,
            conversation_id=conv_id,
            run_id=run_id,
            agent_id=agent_id,
        )
        session.close()

        trace["stages"].append(
            {
                "stage": "3_checkpoint",
                "checkpoint_id": checkpoint.checkpoint_id,
                "last_committed_sequence": checkpoint.last_committed_sequence,
                "next_node_id": checkpoint.next_node_id,
                "checkpoint_registry_hash": checkpoint.checkpoint_registry_hash,
                "session_closed": True,
            }
        )

        # ===== Stage 4: Reopen + safe resume decision = ok =====
        reopened = SessionService.reopen(
            repo,
            conversation_id=conv_id,
            run_id=run_id,
            agent_id=agent_id,
        )
        coordinator = ResumeCoordinator(
            registry=registry,
            file_verifier=FileSnapshotVerifier(),
        )
        decision = coordinator.decide_resume(reopened)

        # Assert: clean resume — no pending operations, no file conflicts.
        assert decision.status == "ok", (
            f"expected ok, got {decision.status}: {decision.reason}"
        )
        assert decision.can_auto_resume is True
        assert decision.next_node_id == "node-A"
        assert decision.last_safe_sequence == 1

        trace["stages"].append(
            {
                "stage": "4_safe_resume",
                "decision_status": decision.status,
                "can_auto_resume": decision.can_auto_resume,
                "next_node_id": decision.next_node_id,
                "last_safe_sequence": decision.last_safe_sequence,
                "recommended_action": decision.recommended_action,
                "pending_operations_count": len(decision.pending_operations),
            }
        )

        # ===== Stage 5: Inject pending mutation → recovery_required =====
        # Emit operation.started without a matching terminal event. This
        # simulates a crash mid-mutation: the side effect is in flight,
        # its outcome is unknown, and resume MUST NOT auto-replay it.
        reopened.emit(
            "operation.started",
            {"operation_id": "op-file-write-1"},
            agent_id=agent_id,
        )
        decision2 = coordinator.decide_resume(reopened)

        # Assert: recovery_required — never auto-replay a mutation.
        assert decision2.status == "recovery_required", (
            f"expected recovery_required, got {decision2.status}: "
            f"{decision2.reason}"
        )
        assert decision2.can_auto_resume is False
        assert decision2.recommended_action == "initiate_recovery"
        # The pending operation must be surfaced for the recovery shell.
        assert len(decision2.pending_operations) == 1
        assert decision2.pending_operations[0]["operation_id"] == "op-file-write-1"

        trace["stages"].append(
            {
                "stage": "5_unsafe_resume",
                "decision_status": decision2.status,
                "can_auto_resume": decision2.can_auto_resume,
                "reason": decision2.reason,
                "recommended_action": decision2.recommended_action,
                "pending_operations": list(decision2.pending_operations),
            }
        )

        # ===== Export trace JSON =====
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        trace_path = ARTIFACT_DIR / "mvp_demo_trace.json"
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2, ensure_ascii=False)

    finally:
        repo.close()
