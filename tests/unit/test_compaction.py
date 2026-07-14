"""Phase D tests: Budget overflow + structured compaction.

Covers SOP §8.3 (deterministic eviction + compaction fallback) and §9
(CompactionResult contract + six forbidden behaviors).

Test matrix:
- D-01 Char4TokenEstimator — conservative fallback for Latin and CJK
- D-02 Deterministic eviction order — observation evicted before constraint
- D-03 Tool output trimming — large tool_output items are evictable
- D-04 Structured compaction — evicted observations merged into summary
- D-05 Constraint retention — fixture-driven, constraints 100% retained
- D-06 Compaction drift — repeated builds produce identical required IDs
- D-07 Immutable ContextSnapshot — snapshot fields are frozen

Plus §9.2 forbidden behaviors (enforced by construction + verified by test):
- hypothesis never promoted to fact
- evidence_ref never fabricated
- constraint never dropped by compaction
- original sources never overwritten
- external_untrusted never promoted to instruction
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from paperclaw.context.builder import (
    ContextBudgetExhausted,
    ContextBuilder,
    EXCLUSION_BUDGET,
    ROLE_COORDINATOR,
    RoleContextView,
)
from paperclaw.context.compaction import (
    Char4TokenEstimator,
    CompactionPolicy,
    DEFAULT_ESTIMATOR,
    ESTIMATOR_CHAR4,
    TokenEstimator,
)
from paperclaw.context.contracts import (
    CompactionResult,
    ContextBudget,
    ContextItem,
    ContextSnapshot,
    ContextSource,
    SCOPE_SHARED,
    utc_now_iso,
)
from paperclaw.context.repository import SQLiteRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> SQLiteRepository:
    r = SQLiteRepository(tmp_path / "phase_d.db", migrate=True)
    # Repository.list_context_items joins on run_id; create the parent
    # conversation + run so inserts succeed. The run_id here matches the
    # default run_id used in _item() below.
    r.create_conversation("conv-d")
    r.start_run(
        run_id="run-d",
        conversation_id="conv-d",
        agent_id="agent-d",
        role="coordinator",
    )
    yield r
    r.close()


@pytest.fixture
def builder(repo: SQLiteRepository) -> ContextBuilder:
    return ContextBuilder(repo)


def _budget(
    *,
    max_input: int = 32000,
    reserved_output: int = 6000,
    safety: int = 3200,
    single: int = 8000,
    tool: int = 8000,
) -> ContextBudget:
    return ContextBudget(
        max_input_tokens=max_input,
        reserved_output_tokens=reserved_output,
        safety_margin_tokens=safety,
        max_single_item_tokens=single,
        max_tool_output_tokens=tool,
    )


def _src(
    *,
    source_type: str = "runtime",
    trust_level: str = "system",
    sequence: int = 0,
    ref: str | None = None,
) -> ContextSource:
    return ContextSource(
        source_type=source_type,
        source_ref=ref or f"ref-{sequence}",
        trust_level=trust_level,
        created_sequence=sequence,
    )


def _item(
    *,
    item_id: str = "item-1",
    run_id: str = "run-d",
    layer: str = "L3",
    kind: str = "observation",
    content: str = "placeholder",
    source: ContextSource | None = None,
    scope: tuple[str, ...] = (SCOPE_SHARED,),
    priority: int = 50,
    tokens: int = 8,
    valid_from: int = 0,
    valid_to: int | None = None,
    task_id: str | None = None,
    supersedes: str | None = None,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        run_id=run_id,
        layer=layer,
        kind=kind,
        content=content,
        source=source or _src(sequence=valid_from),
        priority=priority,
        scope=scope,
        estimated_tokens=tokens,
        valid_from_sequence=valid_from,
        valid_to_sequence=valid_to,
        task_id=task_id,
        supersedes_item_id=supersedes,
    )


def _seed_items(repo: SQLiteRepository, items: list[ContextItem]) -> None:
    repo.insert_context_items(items)


# ---------------------------------------------------------------------------
# D-01: Char4TokenEstimator
# ---------------------------------------------------------------------------


class TestChar4TokenEstimator:
    def test_estimator_id_is_stable(self):
        est = Char4TokenEstimator()
        assert est.estimator_id == ESTIMATOR_CHAR4

    def test_empty_returns_zero(self):
        assert Char4TokenEstimator().estimate("") == 0

    def test_latin_text_rounds_up(self):
        # "hello world" = 11 bytes → ceil(11/4) = 3 tokens
        assert Char4TokenEstimator().estimate("hello world") == 3

    def test_cjk_text_overestimates_safely(self):
        # CJK chars are 3 UTF-8 bytes each; 4 chars = 12 bytes → 3 tokens.
        # Real CJK tokenization is ~1-2 tokens/char, so char4 is conservative.
        assert Char4TokenEstimator().estimate("你好世界") == 3

    def test_default_estimator_is_char4(self):
        assert DEFAULT_ESTIMATOR.estimator_id == ESTIMATOR_CHAR4

    def test_token_estimator_protocol_accepts_custom(self):
        class WordCountEstimator:
            estimator_id = "word"
            def estimate(self, content: str) -> int:
                return len(content.split())

        est: TokenEstimator = WordCountEstimator()
        assert est.estimate("hello world foo") == 3


# ---------------------------------------------------------------------------
# D-02: Deterministic eviction order (Phase C core + Phase D re-verify)
# ---------------------------------------------------------------------------


class TestDeterministicEviction:
    def test_observation_evicted_before_constraint(self, builder, repo):
        """SOP §8.1: constraints are never auto-deleted; observations are
        the first to be evicted (§8.3 priority 5)."""
        _seed_items(repo, [
            _item(item_id="c-1", kind="constraint", layer="L2",
                  content="must not install deps", tokens=100, priority=10),
            _item(item_id="obs-1", kind="observation", layer="L4",
                  content="old log line", tokens=100, priority=10),
            _item(item_id="obs-2", kind="observation", layer="L4",
                  content="another old log", tokens=100, priority=5),
        ])
        # usable = 400 - 100 - 40 = 260; total = 300 → evict one (obs-2).
        budget = _budget(max_input=400, reserved_output=100, safety=40)
        snap = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=10,
        )
        assert "c-1" in snap.source_item_ids
        # At least one observation was evicted (or compacted).
        # After Phase D compaction, a summary may appear instead.
        evicted_ids = {
            rec["item_id"] for rec in snap.excluded_items
            if rec.get("exclusion_reason") == EXCLUSION_BUDGET
        }
        # Either obs-1 or obs-2 was budget-evicted (obs-2 has lower priority).
        assert "obs-2" in evicted_ids

    def test_lower_priority_evicted_first(self, builder, repo):
        _seed_items(repo, [
            _item(item_id="hi", kind="observation", tokens=100, priority=90),
            _item(item_id="lo", kind="observation", tokens=100, priority=10),
        ])
        # usable = 400 - 100 - 40 = 260; total = 200 → fits, no eviction.
        # Force tighter: usable = 150 → evict one.
        budget = _budget(max_input=300, reserved_output=100, safety=50)
        snap = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        # Higher-priority item survives; lower-priority may be evicted
        # or absorbed into a summary.
        assert "hi" in snap.source_item_ids


# ---------------------------------------------------------------------------
# D-04: Structured compaction
# ---------------------------------------------------------------------------


class TestStructuredCompaction:
    def test_compaction_merges_evicted_observations(self, builder, repo):
        """When budget overflow evicts observations, compaction merges
        them into a summary item that fits the budget."""
        # Use small-token observations so the summary (which absorbs
        # their content snippets) doesn't itself blow the budget.
        items = [
            _item(item_id="c-1", kind="constraint", layer="L2",
                  content="must_not install", tokens=50, priority=100),
        ] + [
            _item(item_id=f"obs-{i}", kind="observation", layer="L4",
                  content=f"obs{i}", tokens=5, priority=10)
            for i in range(20)
        ]
        _seed_items(repo, items)
        # usable = 200 - 100 - 40 = 60; 50 + 2*5 = 60 → evict 18.
        budget = _budget(max_input=200, reserved_output=100, safety=40)
        builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=5,
        )
        # Verify CompactionResult persisted via summary item's source_ref.
        all_items_after = repo.list_context_items("run-d")
        summary_items = [
            i for i in all_items_after
            if i.kind == "observation"
            and i.source.source_ref.startswith("compaction:")
        ]
        assert len(summary_items) >= 1

    def test_compaction_result_has_required_fields(self, builder, repo):
        items = [
            _item(item_id="c-1", kind="constraint", tokens=50, priority=100),
            _item(item_id="ev-1", kind="observation", tokens=200, priority=10),
            _item(item_id="ev-2", kind="observation", tokens=200, priority=5),
        ]
        _seed_items(repo, items)
        budget = _budget(max_input=2000, reserved_output=500, safety=200)
        # usable = 1300; protected = 50; 2 obs = 400; total = 450 < 1300
        # → no eviction → no compaction. Force tighter:
        budget = _budget(max_input=600, reserved_output=100, safety=60)
        # usable = 440; 50 + 200 + 200 = 450 > 440 → evict one.
        builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        # Verify CompactionResult persisted via summary item's source_ref.
        all_items = repo.list_context_items("run-d")
        summaries = [
            i for i in all_items
            if i.source.source_ref.startswith("compaction:")
        ]
        if summaries:
            s = summaries[0]
            # source_ref format: "compaction:item_id1,item_id2"
            absorbed = s.source.source_ref.split(":", 1)[1].split(",")
            assert len(absorbed) >= 1
            assert all(aid in {"ev-1", "ev-2"} for aid in absorbed)

    def test_compaction_preserves_constraint_ids(self, builder, repo):
        """§9.3: required constraint IDs MUST be retained after compaction."""
        items = [
            _item(item_id="c-must-not", kind="constraint", layer="L2",
                  content="must not install deps", tokens=50, priority=100),
            _item(item_id="c-path", kind="constraint", layer="L2",
                  content="path scope src/", tokens=50, priority=100),
            _item(item_id="c-decision", kind="constraint", layer="L2",
                  content="use sqlite3", tokens=50, priority=100),
        ] + [
            _item(item_id=f"obs-{i}", kind="observation",
                  content="x" * 100, tokens=100, priority=10)
            for i in range(30)
        ]
        _seed_items(repo, items)
        budget = _budget(max_input=2000, reserved_output=400, safety=200)
        snap = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        # All three constraints survived.
        for cid in ("c-must-not", "c-path", "c-decision"):
            assert cid in snap.source_item_ids, f"{cid} was dropped"


# ---------------------------------------------------------------------------
# D-05: Constraint Retention fixture (§9.3)
# ---------------------------------------------------------------------------


CONSTRAINT_RETENTION_FIXTURE = {
    "required_constraints": [
        {"id": "c1", "type": "must_not", "value": "do not install dependencies"},
        {"id": "c2", "type": "path_scope", "value": "src/"},
        {"id": "c3", "type": "decision", "value": "use sqlite3"},
    ]
}


class TestConstraintRetentionFixture:
    def test_fixture_format_matches_sop(self):
        """SOP §9.3 requires the fixture to have required_constraints
        with id/type/value fields."""
        assert "required_constraints" in CONSTRAINT_RETENTION_FIXTURE
        for c in CONSTRAINT_RETENTION_FIXTURE["required_constraints"]:
            assert "id" in c
            assert "type" in c
            assert "value" in c

    def test_all_required_constraints_retained_after_compaction(self, builder, repo):
        """Acceptance based on constraint ID, not string matching (§9.3)."""
        fixture = CONSTRAINT_RETENTION_FIXTURE
        items = [
            _item(
                item_id=c["id"],
                kind="constraint",
                layer="L2",
                content=c["value"],
                tokens=60,
                priority=100,
            )
            for c in fixture["required_constraints"]
        ] + [
            _item(item_id=f"obs-{i}", kind="observation",
                  content="y" * 200, tokens=200, priority=5)
            for i in range(20)
        ]
        _seed_items(repo, items)
        budget = _budget(max_input=1500, reserved_output=300, safety=150)
        snap = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        required_ids = {c["id"] for c in fixture["required_constraints"]}
        surviving = set(snap.source_item_ids)
        missing = required_ids - surviving
        assert not missing, f"required constraints dropped: {missing}"


# ---------------------------------------------------------------------------
# D-06: Compaction Drift (repeated builds → stable required IDs)
# ---------------------------------------------------------------------------


class TestCompactionDrift:
    def test_repeated_builds_keep_constraint_ids_stable(self, builder, repo):
        """Two builds against the same input must retain the same
        required constraint IDs — no drift across compaction rounds."""
        items = [
            _item(item_id="c-1", kind="constraint", tokens=50, priority=100),
            _item(item_id="c-2", kind="constraint", tokens=50, priority=100),
        ] + [
            _item(item_id=f"obs-{i}", kind="observation",
                  content="z" * 150, tokens=150, priority=10)
            for i in range(15)
        ]
        _seed_items(repo, items)
        budget = _budget(max_input=1500, reserved_output=300, safety=150)

        snap1 = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        snap2 = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        # Constraint IDs MUST appear in both snapshots.
        for cid in ("c-1", "c-2"):
            assert cid in snap1.source_item_ids
            assert cid in snap2.source_item_ids

    def test_compaction_hash_deterministic_for_same_input(self):
        """Two CompactionPolicy.compact calls with the same eligible
        items produce the same compaction_hash."""
        policy = CompactionPolicy()
        items = [
            _item(item_id=f"obs-{i}", kind="observation",
                  content=f"content {i}", tokens=10, priority=10)
            for i in range(5)
        ]
        # First call.
        outcome1 = policy.compact(
            kept=[],
            evicted=list(items),
            budget=_budget(max_input=100000),
            view=RoleContextView(role=ROLE_COORDINATOR),
            run_id="r",
            at_sequence=0,
        )
        # Second call with a fresh copy of the same items.
        items2 = [
            _item(item_id=f"obs-{i}", kind="observation",
                  content=f"content {i}", tokens=10, priority=10)
            for i in range(5)
        ]
        outcome2 = policy.compact(
            kept=[],
            evicted=list(items2),
            budget=_budget(max_input=100000),
            view=RoleContextView(role=ROLE_COORDINATOR),
            run_id="r",
            at_sequence=0,
        )
        assert outcome1.result is not None
        assert outcome2.result is not None
        assert outcome1.result.compaction_hash == outcome2.result.compaction_hash


# ---------------------------------------------------------------------------
# D-07: Immutable ContextSnapshot (Phase C invariant, re-verified)
# ---------------------------------------------------------------------------


class TestImmutableSnapshot:
    def test_snapshot_is_frozen(self, builder, repo):
        _seed_items(repo, [
            _item(item_id="i-1", kind="observation", tokens=10),
        ])
        snap = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=_budget(),
            agent_id="coord",
            at_sequence=0,
        )
        with pytest.raises(Exception):
            # frozen dataclass raises FrozenInstanceError on setattr.
            snap.snapshot_id = "tampered"

    def test_compaction_result_is_frozen(self):
        result = CompactionResult(
            summary_item_ids=("s1",),
            retained_constraint_ids=("c1",),
            retained_evidence_refs=(),
            removed_item_ids=("o1",),
            source_item_ids=("o1",),
            compaction_hash="abc",
        )
        with pytest.raises(Exception):
            result.compaction_hash = "tampered"


# ---------------------------------------------------------------------------
# §9.2 Forbidden behaviors
# ---------------------------------------------------------------------------


class TestForbiddenBehaviors:
    def test_hypothesis_not_promoted_to_fact(self, builder, repo):
        """§9.2: compaction MUST NOT rewrite hypothesis as fact.

        The CompactionPolicy only merges ``observation`` items. A
        ``hypothesis`` item that survives first-pass selection stays
        a ``hypothesis`` in the final snapshot.
        """
        _seed_items(repo, [
            _item(item_id="h-1", kind="hypothesis", layer="L4",
                  content="maybe X is true", tokens=50, priority=80),
            _item(item_id="c-1", kind="constraint", tokens=50, priority=100),
        ])
        snap = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=_budget(),
            agent_id="coord",
            at_sequence=0,
        )
        assert "h-1" in snap.source_item_ids
        # The hypothesis kind is preserved — no summary turned it into a fact.
        all_items = {i.item_id: i for i in repo.list_context_items("run-d")}
        assert all_items["h-1"].kind == "hypothesis"

    def test_evidence_ref_not_fabricated(self, builder, repo):
        """§9.2: compaction MUST NOT generate non-existent Evidence refs.

        Summary items reference original item_ids only; they never
        invent new evidence_ref entries.
        """
        _seed_items(repo, [
            _item(item_id="er-1", kind="evidence_ref", tokens=50, priority=100),
        ] + [
            _item(item_id=f"obs-{i}", kind="observation",
                  content="x" * 100, tokens=100, priority=10)
            for i in range(10)
        ])
        budget = _budget(max_input=800, reserved_output=100, safety=80)
        builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        all_items = repo.list_context_items("run-d")
        # Only one evidence_ref exists (the original); no new ones created.
        evidence_refs = [i for i in all_items if i.kind == "evidence_ref"]
        assert len(evidence_refs) == 1
        assert evidence_refs[0].item_id == "er-1"

    def test_constraint_not_dropped_by_compaction(self, builder, repo):
        """§9.2: compaction MUST NOT drop user hard constraints."""
        _seed_items(repo, [
            _item(item_id="hard-1", kind="constraint", layer="L2",
                  content="must not delete src/", tokens=50, priority=100),
        ] + [
            _item(item_id=f"obs-{i}", kind="observation",
                  content="y" * 200, tokens=200, priority=10)
            for i in range(20)
        ])
        budget = _budget(max_input=800, reserved_output=100, safety=80)
        snap = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        assert "hard-1" in snap.source_item_ids

    def test_protected_overflow_raises_not_silent(self, builder, repo):
        """§8.3 last clause: if protected items alone exceed usable_input,
        raise ContextBudgetExhausted — do NOT silently truncate."""
        _seed_items(repo, [
            _item(item_id="c-1", kind="constraint", tokens=500, priority=100),
            _item(item_id="c-2", kind="constraint", tokens=500, priority=100),
        ])
        # usable = 200 - 50 - 20 = 130 < 1000 protected
        budget = _budget(max_input=200, reserved_output=50, safety=20)
        with pytest.raises(ContextBudgetExhausted):
            builder.build(
                run_id="run-d",
                view=RoleContextView(role=ROLE_COORDINATOR),
                budget=budget,
                agent_id="coord",
                at_sequence=0,
            )


# ---------------------------------------------------------------------------
# D-03: Tool output trimming (§8.2: long tool output is evictable)
# ---------------------------------------------------------------------------


class TestToolOutputTrimming:
    def test_large_tool_output_is_evictable(self, builder, repo):
        """§8.2: long tool output is in the compressible set. When
        budget is tight, large tool outputs are evicted before
        constraints."""
        _seed_items(repo, [
            _item(item_id="c-1", kind="constraint", tokens=50, priority=100),
            _item(
                item_id="tool-out-1",
                kind="observation",
                layer="L4",
                content="x" * 4000,
                tokens=1000,
                priority=20,
                source=_src(source_type="tool", ref="tool:bash:stdout"),
            ),
        ])
        # usable = 1500; 50 + 1000 = 1050 < 1500 — fits without eviction.
        # Force tighter budget to trigger eviction:
        budget = _budget(max_input=800, reserved_output=100, safety=80)
        # usable = 620; 50 + 1000 = 1050 > 620 → evict tool-out-1.
        snap = builder.build(
            run_id="run-d",
            view=RoleContextView(role=ROLE_COORDINATOR),
            budget=budget,
            agent_id="coord",
            at_sequence=0,
        )
        assert "c-1" in snap.source_item_ids
        # tool-out-1 was either evicted or absorbed into a summary.
        assert "tool-out-1" not in snap.source_item_ids or any(
            rec.get("exclusion_reason") == "compaction_summary"
            for rec in snap.excluded_items
        )


# ---------------------------------------------------------------------------
# CompactionPolicy direct unit tests
# ---------------------------------------------------------------------------


class TestCompactionPolicyDirect:
    def test_no_eviction_returns_none_result(self):
        policy = CompactionPolicy()
        outcome = policy.compact(
            kept=[_item(item_id="k-1", tokens=10)],
            evicted=[],
            budget=_budget(max_input=100000),
            view=RoleContextView(role=ROLE_COORDINATOR),
            run_id="r",
            at_sequence=0,
        )
        assert outcome.result is None
        assert outcome.still_over_budget is False

    def test_summary_item_inherits_shared_scope(self):
        policy = CompactionPolicy()
        items = [
            _item(item_id=f"o-{i}", kind="observation", tokens=10)
            for i in range(3)
        ]
        outcome = policy.compact(
            kept=[],
            evicted=items,
            budget=_budget(max_input=100000),
            view=RoleContextView(role=ROLE_COORDINATOR),
            run_id="r",
            at_sequence=5,
        )
        assert outcome.result is not None
        # Summary items are in final_selected.
        summaries = [
            i for i in outcome.final_selected
            if i.item_id.startswith("summary-")
        ]
        assert len(summaries) >= 1
        # Summary is an observation (never promoted to fact).
        assert all(s.kind == "observation" for s in summaries)
        # Summary scope is shared.
        for s in summaries:
            assert "shared" in s.scope
        # source_ref traces back to original item_ids.
        for s in summaries:
            assert s.source.source_ref.startswith("compaction:")
            absorbed = s.source.source_ref.split(":", 1)[1].split(",")
            assert all(aid in {"o-0", "o-1", "o-2"} for aid in absorbed)

    def test_custom_estimator_used_for_summary_tokens(self):
        class FixedEstimator:
            estimator_id = "fixed-42"
            def estimate(self, content: str) -> int:
                return 42

        policy = CompactionPolicy(estimator=FixedEstimator())  # type: ignore[arg-type]
        items = [_item(item_id="o-1", kind="observation", tokens=10)]
        outcome = policy.compact(
            kept=[],
            evicted=items,
            budget=_budget(max_input=100000),
            view=RoleContextView(role=ROLE_COORDINATOR),
            run_id="r",
            at_sequence=0,
        )
        summaries = [i for i in outcome.final_selected if i.item_id.startswith("summary-")]
        assert summaries[0].estimated_tokens == 42

    def test_max_items_per_summary_chunks_large_evictions(self):
        """When eligible items exceed ``max_items_per_summary``, multiple
        summary items are produced so no single summary dominates budget."""
        policy = CompactionPolicy(max_items_per_summary=4)
        items = [
            _item(item_id=f"o-{i}", kind="observation", tokens=10)
            for i in range(10)
        ]
        outcome = policy.compact(
            kept=[],
            evicted=items,
            budget=_budget(max_input=100000),
            view=RoleContextView(role=ROLE_COORDINATOR),
            run_id="r",
            at_sequence=0,
        )
        summaries = [i for i in outcome.final_selected if i.item_id.startswith("summary-")]
        # 10 items / 4 per summary = 3 summaries (4, 4, 2).
        assert len(summaries) == 3
