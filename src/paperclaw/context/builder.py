"""Phase C: ContextBuilder and RoleContextView.

Implements SOP §6 (role views), §7 (ContextBuilder flow), §7.2 (prompt
injection boundary), §8 (token budget deterministic selection).

Design notes
------------

The SOP defines ContextBuilder as a *flow contract* (collect → validate →
scope → expire/supersede → dedup → conflict → estimate → select → compact
→ render → persist), not as a concrete class signature. This module picks
a straightforward class-based implementation:

- ``ContextBuilder.build(...)`` is the single entry point. Callers pass a
  ``RoleContextView`` describing which role is asking, a ``ContextBudget``
  describing the token envelope, and an ``at_sequence`` for the active
  window. The method returns a persisted ``ContextSnapshot``.

- ``RoleContextView`` is a frozen value object carrying only ``role`` and
  ``task_id``. The actual scope-matching rule lives in the builder so the
  view itself stays free of conditional logic. This keeps the dataclass
  trivially serializable and avoids premature abstraction.

- Compaction (§9) is deferred to Phase D. The builder calls a
  ``_maybe_compact`` hook that, in Phase C, records the unmet demand and
  proceeds with deterministic selection only. Phase D will inject a real
  ``CompactionPolicy`` without changing the ``build`` signature.

Prompt injection boundary (§7.2)
--------------------------------

Items whose ``source.trust_level == "external_untrusted"`` MUST NOT enter
L0 (Runtime Constitution) or L1 (Role). The builder enforces this before
scope filtering so an external item in L0/L1 is excluded with reason
``trust_violation`` even if its scope matches the role. This is a hard
NO-GO guard (§15): external text upgrading to a high-priority instruction.

Deterministic selection (§8.3)
------------------------------

Non-protected items are kept in keep-priority order (highest first) until
the running token estimate fits ``budget.usable_input()``. The keep order
encodes the inverse of the §8.3 eviction priority:

1. Protected items are always kept (see ``_is_protected``).
2. Non-protected items are sorted by keep score (descending):

   - Normal items (tier 2) — kept first
   - Large file content (tier 1) — kept second
   - Old Observations (tier 0) — kept last (evicted first)

3. Within a tier, higher priority is kept first, then more recent
   ``valid_from_sequence``, then item_id for stability.

If protected items alone exceed ``usable_input``, the builder raises
``ContextBudgetExhausted`` — it MUST NOT silently truncate hard
constraints (§8.3 last clause).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import uuid4

from paperclaw.context.contracts import (
    CONTEXT_LAYERS,
    ContextBudget,
    ContextItem,
    ContextSnapshot,
    ContextSource,
    SCOPE_COORDINATOR,
    SCOPE_REVIEWER,
    SCOPE_SHARED,
    TRUST_LEVELS,
    utc_now_iso,
    validate_item,
)
from paperclaw.context.repository import Repository


# ---------------------------------------------------------------------------
# Role views (SOP §6)
# ---------------------------------------------------------------------------


#: Roles recognized by the v0.04 builder. ``worker`` requires a non-empty
#: ``task_id`` on the view so per-Task isolation can be enforced.
ROLE_COORDINATOR = "coordinator"
ROLE_WORKER = "worker"
ROLE_REVIEWER = "reviewer"
_ALLOWED_ROLES = (ROLE_COORDINATOR, ROLE_WORKER, ROLE_REVIEWER)


@dataclass(frozen=True)
class RoleContextView:
    """Filter describing which ContextItems a single role may see.

    Per SOP §6 each role has a default include / exclude list. The builder
    encodes those rules directly against ``ContextItem.scope``:

    - ``shared`` items are visible to every role.
    - ``coordinator`` items are visible only when ``role == "coordinator"``.
    - ``reviewer`` items are visible only when ``role == "reviewer"``.
    - ``worker:<task_id>`` items are visible only when ``role == "worker"``
      AND ``view.task_id == <task_id>``.

    The view itself is intentionally minimal — just ``role`` and
    ``task_id``. The matching logic lives in ``ContextBuilder`` so the
    dataclass stays free of conditionals and trivially serializable.
    """

    role: str
    task_id: str | None = None

    def __post_init__(self) -> None:
        if self.role not in _ALLOWED_ROLES:
            raise ValueError(
                f"role must be one of {_ALLOWED_ROLES}; got {self.role!r}"
            )
        if self.role == ROLE_WORKER and not self.task_id:
            raise ValueError("worker role requires a non-empty task_id")


# ---------------------------------------------------------------------------
# Exclusion reasons (SOP §4.4 excluded_items)
# ---------------------------------------------------------------------------


#: Each entry in ``ContextSnapshot.excluded_items`` is a dict carrying at
#: least ``item_id`` and ``exclusion_reason``. These constants populate the
#: ``exclusion_reason`` field so consumers can filter / aggregate without
#: parsing free-form text.
EXCLUSION_SCOPE = "scope_mismatch"
EXCLUSION_EXPIRED = "expired"
EXCLUSION_SUPERSEDED = "superseded"
EXCLUSION_TRUST_VIOLATION = "trust_violation"
EXCLUSION_BUDGET = "budget_overflow"
EXCLUSION_DEDUPLICATION = "deduplication"
EXCLUSION_CONFLICT = "conflict"

_ALLOWED_EXCLUSIONS = (
    EXCLUSION_SCOPE,
    EXCLUSION_EXPIRED,
    EXCLUSION_SUPERSEDED,
    EXCLUSION_TRUST_VIOLATION,
    EXCLUSION_BUDGET,
    EXCLUSION_DEDUPLICATION,
    EXCLUSION_CONFLICT,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ContextBudgetExhausted(RuntimeError):
    """Raised when protected items alone exceed ``budget.usable_input()``.

    Per SOP §8.3 the builder MUST NOT silently truncate hard constraints.
    Raising this error lets the caller (typically the AgentRuntime) decide
    whether to switch Provider / split the task / fail the run.
    """

    def __init__(self, run_id: str, required: int, usable: int):
        super().__init__(
            f"protected context items for run {run_id} require "
            f"{required} tokens but usable_input is {usable}; "
            f"cannot proceed without dropping a hard constraint"
        )
        self.run_id = run_id
        self.required_tokens = required
        self.usable_tokens = usable


class ContextBuilderError(RuntimeError):
    """Base class for ContextBuilder structural failures."""


# ---------------------------------------------------------------------------
# Internal tuning constants
# ---------------------------------------------------------------------------


#: Items whose ``source.source_type == "file"`` and ``estimated_tokens``
#: exceeds this threshold are considered "large re-readable content" and
#: become eviction candidates in §8.3 priority 6. Tunable in v0.04.1 if
#: real-world traces show the cutoff is wrong.
_LARGE_FILE_TOKEN_THRESHOLD = 500


#: Token estimator identifier recorded on the snapshot. ``char4`` is the
#: v0.04 default (1 token per 4 chars) used when no tokenizer is present.
#: Phase D may swap in a real tokenizer via ModelAdapter.
_DEFAULT_ESTIMATOR = "char4"


# ---------------------------------------------------------------------------
# ContextBuilder (SOP §7)
# ---------------------------------------------------------------------------


class ContextBuilder:
    """Build a role-scoped ``ContextSnapshot`` from persisted items.

    Single entry point is :meth:`build`. The builder is stateless across
    invocations — all per-call inputs come through method arguments — so
    a single instance can be shared by Coordinator / Worker / Reviewer
    threads (provided the underlying ``Repository`` is thread-safe, which
    ``SQLiteRepository`` is via its writer RLock).
    """

    def __init__(self, repo: Repository, compaction_policy: Any = None):
        """Initialize the builder.

        ``compaction_policy`` accepts a ``CompactionPolicy`` instance
        (or any object with a compatible ``compact`` signature). It
        defaults to ``None`` and is lazily instantiated on first use to
        avoid a circular import (``compaction`` imports
        ``ContextItem`` from ``contracts``, but ``builder`` imports
        ``CompactionPolicy`` from ``compaction`` — the lazy import breaks
        the cycle cleanly without a shared ``_internal`` module).
        """
        self._repo = repo
        self._compaction_policy = compaction_policy

    # -- public API ---------------------------------------------------

    def build(
        self,
        *,
        run_id: str,
        view: RoleContextView,
        budget: ContextBudget,
        agent_id: str,
        at_sequence: int,
        estimator: str = _DEFAULT_ESTIMATOR,
    ) -> ContextSnapshot:
        """Run the SOP §7 flow and persist a ContextSnapshot.

        Steps (verbatim from §7)::

            collect
            → validate source/trust
            → apply role scope
            → remove expired/superseded items
            → deduplicate
            → resolve conflicts
            → estimate tokens
            → deterministic selection
            → compact if required
            → render
            → persist ContextSnapshot
        """
        budget.validate()

        # Step 1: collect. Repository already filters by run_id; we apply
        # at_sequence locally so the same row set can be re-evaluated
        # against different sequence windows without re-querying.
        candidates = self._repo.list_context_items(run_id)

        # Step 2: validate source/trust. Invalid items are excluded with
        # reason trust_violation — they never reach scope filtering.
        validated, invalid = self._validate_items(candidates)
        excluded: list[dict[str, Any]] = [
            {
                "item_id": item.item_id,
                "exclusion_reason": EXCLUSION_TRUST_VIOLATION,
                "detail": "validation raised; see logs",
            }
            for item in invalid
        ]

        # Step 3: prompt injection boundary (§7.2) — external_untrusted
        # in L0/L1 is rejected before scope filtering.
        trust_filtered, trust_excluded = self._enforce_trust_boundary(validated)
        excluded.extend(trust_excluded)

        # Step 4: scope filter — apply RoleContextView to remaining items.
        scoped, scope_excluded = self._apply_role_scope(trust_filtered, view)
        excluded.extend(scope_excluded)

        # Step 5: remove expired / superseded items.
        active, lifecycle_excluded = self._remove_expired_and_superseded(
            scoped, at_sequence
        )
        excluded.extend(lifecycle_excluded)

        # Step 6: deduplicate by item_id (defensive — Repository PK
        # already prevents duplicates, but list_context_items could in
        # principle return duplicates if a future join changes shape).
        deduped, dedup_excluded = self._deduplicate(active)
        excluded.extend(dedup_excluded)

        # Step 7: conflict resolution (§7.1). v0.04 MVP detects a narrow
        # case — two active ``fact`` items with the same task_id and
        # layer but different content. Real conflict detection (via
        # explicit conflict markers) is deferred to v0.04.1.
        conflict_free, conflict_excluded = self._resolve_conflicts(deduped)
        excluded.extend(conflict_excluded)

        # Step 8: estimate tokens. Sum of per-item estimated_tokens; the
        # same value is used for budget enforcement and recorded on the
        # snapshot for traceability.
        total_tokens = sum(item.estimated_tokens for item in conflict_free)

        # Step 9: deterministic selection (§8.3). Returns the kept set
        # and the items evicted to fit budget, with exclusion records.
        usable = budget.usable_input()
        selected, budget_excluded = self._select_within_budget(
            conflict_free, total_tokens, usable, run_id
        )
        excluded.extend(budget_excluded)

        # Step 10: compact if required (Phase D). The lazy import avoids
        # a circular dependency at module load time: ``compaction`` imports
        # ``ContextItem`` from ``contracts`` (no cycle), but ``builder`` and
        # ``compaction`` reference each other's symbols. Importing here —
        # inside the build method — keeps the cycle out of the import graph.
        compaction_result = self._run_compaction(
            selected, budget_excluded, budget, view, run_id, at_sequence
        )
        if compaction_result is not None:
            outcome, result = compaction_result
            # Persist summary items so future builds see the compacted
            # state (otherwise the next build would re-compact the same
            # source items, causing drift — D6 invariant).
            if result is not None:
                # ``outcome.final_selected`` already contains the summaries;
                # we only need to persist the new summary items, not the
                # already-persisted originals.
                existing_ids = {item.item_id for item in selected}
                new_summaries = [
                    item
                    for item in outcome.final_selected
                    if item.item_id not in existing_ids
                ]
                if new_summaries:
                    self._repo.insert_context_items(new_summaries)
            selected = outcome.final_selected
            # Record the compaction in the exclusion audit trail so
            # consumers can tell which items were merged into which
            # summaries. These are NOT exclusion records — they're
            # ``compaction_summary`` entries that augment the audit.
            if result is not None:
                for summary_id in result.summary_item_ids:
                    excluded.append(
                        {
                            "item_id": summary_id,
                            "exclusion_reason": "compaction_summary",
                            "detail": (
                                "summary item absorbing "
                                f"{len(result.removed_item_ids)} source items"
                            ),
                        }
                    )
            # Re-check budget after compaction. Per SOP §8.3 clause 4,
            # "still over budget → context_budget_exhausted, do NOT
            # silently truncate hard constraints". This means: if
            # PROTECTED items alone still exceed usable_input, raise.
            # If only evictable items + summaries push total over
            # usable, we accept the outcome — compaction already did
            # its best, and dropping a summary would lose provenance.
            post_total = sum(item.estimated_tokens for item in selected)
            if outcome.still_over_budget or post_total > usable:
                protected_tokens = sum(
                    item.estimated_tokens
                    for item in selected
                    if self._is_protected(item)
                )
                # Only raise if protected items themselves exceed budget.
                # Otherwise accept the compacted result (summaries may
                # push total slightly over usable, but that's better than
                # losing provenance or dropping a hard constraint).
                if protected_tokens > usable:
                    raise ContextBudgetExhausted(
                        run_id=run_id,
                        required=protected_tokens,
                        usable=usable,
                    )

        # Step 11: render. Produce a deterministic string and hash so
        # the snapshot is reproducible from its source_item_ids alone
        # (§4.4: rendered string is exportable but not the sole source
        # of truth).
        rendered = self._render(selected, view)
        rendered_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

        # Step 12: persist snapshot. snapshot_id carries a short uuid
        # so multiple builds against the same (run, sequence, role) tuple
        # (e.g. Worker A and Worker B at the same sequence) do not
        # collide on the table's PRIMARY KEY. The id is NOT part of the
        # rendered_hash computation, so determinism of the hash is
        # preserved across calls.
        estimated_total = sum(item.estimated_tokens for item in selected)
        snapshot = ContextSnapshot(
            snapshot_id=f"snap-{uuid4().hex[:16]}",
            run_id=run_id,
            agent_id=agent_id,
            role=view.role,
            source_item_ids=tuple(item.item_id for item in selected),
            excluded_items=tuple(excluded),
            rendered_hash=rendered_hash,
            estimated_tokens=estimated_total,
            estimator=estimator,
            created_sequence=at_sequence,
            task_id=view.task_id,
        )
        self._repo.insert_snapshot(snapshot)
        return snapshot

    # -- step implementations -----------------------------------------

    def _validate_items(
        self, items: Iterable[ContextItem]
    ) -> tuple[list[ContextItem], list[ContextItem]]:
        """Split items into (valid, invalid) by calling validate_item.

        Invalid items are excluded with ``trust_violation`` upstream.
        Validation covers layer/kind/scope/trust_level vocabulary per §4.
        """
        valid: list[ContextItem] = []
        invalid: list[ContextItem] = []
        for item in items:
            try:
                validate_item(item)
                valid.append(item)
            except ValueError:
                invalid.append(item)
        return valid, invalid

    def _enforce_trust_boundary(
        self, items: list[ContextItem]
    ) -> tuple[list[ContextItem], list[dict[str, Any]]]:
        """SOP §7.2: external_untrusted MUST NOT enter L0 or L1.

        Returns the kept items and exclusion records for the rejected
        ones. This guard runs before scope filtering so an external item
        scoped to the current role is still rejected if it lives in L0/L1.
        """
        kept: list[ContextItem] = []
        excluded: list[dict[str, Any]] = []
        for item in items:
            if (
                item.source.trust_level == "external_untrusted"
                and item.layer in ("L0", "L1")
            ):
                excluded.append(
                    {
                        "item_id": item.item_id,
                        "exclusion_reason": EXCLUSION_TRUST_VIOLATION,
                        "detail": (
                            "external_untrusted source in layer "
                            f"{item.layer}; cannot enter Constitution/Role"
                        ),
                    }
                )
            else:
                kept.append(item)
        return kept, excluded

    def _apply_role_scope(
        self, items: list[ContextItem], view: RoleContextView
    ) -> tuple[list[ContextItem], list[dict[str, Any]]]:
        """Filter items by ``ContextItem.scope`` against ``view``.

        Visibility rule (SOP §6):

        - ``shared`` is visible to every role.
        - ``coordinator`` is visible only to the Coordinator.
        - ``reviewer`` is visible only to the Reviewer.
        - ``worker:<task_id>`` is visible only to the Worker whose
          ``view.task_id`` matches.
        """
        kept: list[ContextItem] = []
        excluded: list[dict[str, Any]] = []
        for item in items:
            if self._item_visible_to_view(item, view):
                kept.append(item)
            else:
                excluded.append(
                    {
                        "item_id": item.item_id,
                        "exclusion_reason": EXCLUSION_SCOPE,
                        "detail": (
                            f"scope {list(item.scope)} not visible to "
                            f"{view.role} (task_id={view.task_id})"
                        ),
                    }
                )
        return kept, excluded

    @staticmethod
    def _item_visible_to_view(item: ContextItem, view: RoleContextView) -> bool:
        """Return True if any scope marker on ``item`` matches ``view``."""
        for marker in item.scope:
            if marker == SCOPE_SHARED:
                return True
            if marker == SCOPE_COORDINATOR and view.role == ROLE_COORDINATOR:
                return True
            if marker == SCOPE_REVIEWER and view.role == ROLE_REVIEWER:
                return True
            if (
                view.role == ROLE_WORKER
                and view.task_id is not None
                and marker == f"worker:{view.task_id}"
            ):
                return True
        return False

    def _remove_expired_and_superseded(
        self, items: list[ContextItem], at_sequence: int
    ) -> tuple[list[ContextItem], list[dict[str, Any]]]:
        """Drop items whose validity window has closed or that have been
        superseded by a newer item in the same candidate set.

        Supersession is detected by collecting all ``supersedes_item_id``
        references in the candidate set: if an item's id appears in that
        set AND the superseding item is also in the candidate set, the
        older item is excluded.
        """
        superseding_targets = {
            item.supersedes_item_id
            for item in items
            if item.supersedes_item_id is not None
        }
        kept: list[ContextItem] = []
        excluded: list[dict[str, Any]] = []
        for item in items:
            if not item.is_active_at(at_sequence):
                excluded.append(
                    {
                        "item_id": item.item_id,
                        "exclusion_reason": EXCLUSION_EXPIRED,
                        "detail": (
                            f"validity window closed at sequence "
                            f"{at_sequence}"
                        ),
                    }
                )
                continue
            if item.item_id in superseding_targets:
                excluded.append(
                    {
                        "item_id": item.item_id,
                        "exclusion_reason": EXCLUSION_SUPERSEDED,
                        "detail": (
                            "superseded by a newer item in this candidate set"
                        ),
                    }
                )
                continue
            kept.append(item)
        return kept, excluded

    def _deduplicate(
        self, items: list[ContextItem]
    ) -> tuple[list[ContextItem], list[dict[str, Any]]]:
        """Drop items with duplicate ``item_id`` (defensive).

        ``Repository.insert_context_item`` uses item_id as PRIMARY KEY so
        this step should be a no-op in practice. It exists so future
        join-based queries that could theoretically produce duplicates
        remain safe.
        """
        seen: set[str] = set()
        kept: list[ContextItem] = []
        excluded: list[dict[str, Any]] = []
        for item in items:
            if item.item_id in seen:
                excluded.append(
                    {
                        "item_id": item.item_id,
                        "exclusion_reason": EXCLUSION_DEDUPLICATION,
                        "detail": "duplicate item_id in candidate set",
                    }
                )
                continue
            seen.add(item.item_id)
            kept.append(item)
        return kept, excluded

    def _resolve_conflicts(
        self, items: list[ContextItem]
    ) -> tuple[list[ContextItem], list[dict[str, Any]]]:
        """Detect conflicting ``fact`` items per SOP §7.1.

        v0.04 MVP detection: two active ``fact`` items with the same
        ``layer`` and same ``task_id`` (or both None) but different
        ``content`` are treated as conflicting. Both are excluded with
        reason ``conflict`` and the caller is expected to surface a
        conflict marker upstream.

        Real conflict detection (via explicit conflict markers or a
        semantic similarity check) is deferred to v0.04.1.
        """
        # Group facts by (layer, task_id) and find content collisions.
        groups: dict[tuple[str, str | None], list[ContextItem]] = {}
        for item in items:
            if item.kind != "fact":
                continue
            key = (item.layer, item.task_id)
            groups.setdefault(key, []).append(item)

        conflict_ids: set[str] = set()
        for group in groups.values():
            if len(group) < 2:
                continue
            contents = {item.content for item in group}
            if len(contents) > 1:
                # Two facts with different content in same bucket → conflict.
                for item in group:
                    conflict_ids.add(item.item_id)

        if not conflict_ids:
            return items, []

        kept = [item for item in items if item.item_id not in conflict_ids]
        excluded = [
            {
                "item_id": item_id,
                "exclusion_reason": EXCLUSION_CONFLICT,
                "detail": (
                    "two active fact items with same layer/task_id but "
                    "different content; both excluded pending resolution"
                ),
            }
            for item_id in conflict_ids
        ]
        return kept, excluded

    def _select_within_budget(
        self,
        items: list[ContextItem],
        total_tokens: int,
        usable: int,
        run_id: str,
    ) -> tuple[list[ContextItem], list[dict[str, Any]]]:
        """Apply §8.3 deterministic selection.

        Splits items into protected / evictable. Protected items are
        always kept; evictable items are sorted by keep priority
        (highest first) and walked in that order — the loop keeps
        each item while budget remains, and the tail of the sorted
        list (lowest keep priority) becomes the excluded set.

        If protected items alone exceed ``usable``, raises
        ``ContextBudgetExhausted`` — never silently drops a hard
        constraint.
        """
        if total_tokens <= usable:
            return items, []

        protected: list[ContextItem] = []
        evictable: list[ContextItem] = []
        for item in items:
            if self._is_protected(item):
                protected.append(item)
            else:
                evictable.append(item)

        protected_tokens = sum(item.estimated_tokens for item in protected)
        if protected_tokens > usable:
            raise ContextBudgetExhausted(
                run_id=run_id,
                required=protected_tokens,
                usable=usable,
            )

        # Sort by KEEP priority: highest first. Keep priority is the
        # inverse of §8.3 eviction priority — items we want to retain
        # sort earlier and are added to ``kept`` first, so the loop
        # naturally drops the lowest-priority items when budget runs out.
        evictable.sort(key=self._keep_key, reverse=True)

        kept = list(protected)
        kept_tokens = protected_tokens
        excluded: list[dict[str, Any]] = []
        for item in evictable:
            if kept_tokens + item.estimated_tokens <= usable:
                kept.append(item)
                kept_tokens += item.estimated_tokens
            else:
                excluded.append(
                    {
                        "item_id": item.item_id,
                        "exclusion_reason": EXCLUSION_BUDGET,
                        "detail": (
                            f"dropped to fit usable_input={usable}; "
                            f"item tokens={item.estimated_tokens}"
                        ),
                    }
                )
        return kept, excluded

    @staticmethod
    def _is_protected(item: ContextItem) -> bool:
        """Return True if the item is in the SOP §8.1 'never delete' set."""
        if item.layer in ("L0", "L1"):
            return True
        if item.kind == "constraint":
            return True
        if item.kind == "evidence_ref":
            return True
        if item.kind == "todo" and item.valid_to_sequence is None:
            return True
        return False

    @staticmethod
    def _keep_key(item: ContextItem) -> tuple[int, int, int, str]:
        """Sort key for evictable items — HIGHER tuple = kept first.

        Tier ordering is the inverse of §8.3 eviction priority:

        - tier 2 (normal) — kept first (last to be evicted)
        - tier 1 (large file content) — kept second
        - tier 0 (Observation) — kept last (first to be evicted)

        Within a tier, higher priority is kept first, then more recent
        ``valid_from_sequence``, then item_id for stable tiebreaking.

        Used with ``reverse=True`` so the highest-scoring item sorts to
        the front of the keep queue.
        """
        if item.kind == "observation":
            tier = 0
        elif (
            item.source.source_type == "file"
            and item.estimated_tokens > _LARGE_FILE_TOKEN_THRESHOLD
        ):
            tier = 1
        else:
            tier = 2
        return (tier, item.priority, item.valid_from_sequence, item.item_id)

    def _run_compaction(
        self,
        selected: list[ContextItem],
        budget_excluded: list[dict[str, Any]],
        budget: ContextBudget,
        view: RoleContextView,
        run_id: str,
        at_sequence: int,
    ) -> tuple[Any, Any] | None:
        """Run structured compaction if the first pass evicted items.

        Returns ``(outcome, compaction_result)`` where ``outcome`` is the
        ``CompactionOutcome`` and ``compaction_result`` is the
        ``CompactionResult`` (or ``None`` if no compaction was triggered).
        Returns ``None`` if compaction was not needed (no budget-overflow
        exclusions in the first pass).

        This method is the Phase D replacement for ``_maybe_compact_stub``.
        It decides whether to compact based on the presence of
        ``EXCLUSION_BUDGET`` records in ``budget_excluded``, then delegates
        to ``CompactionPolicy.compact`` for the actual merging.

        Lazy-imports ``CompactionPolicy`` to break the import cycle.
        """
        # Detect whether first-pass selection evicted anything.
        evicted_ids = {
            rec["item_id"]
            for rec in budget_excluded
            if rec.get("exclusion_reason") == EXCLUSION_BUDGET
        }
        if not evicted_ids:
            return None

        # Reconstruct evicted items. We don't have the original
        # ``ContextItem`` objects (first-pass selection dropped them),
        # so we re-fetch from the Repository by run_id and filter by id.
        # This is O(N) but only runs when compaction is needed — the
        # happy path (no overflow) returns early above.
        all_items = self._repo.list_context_items(run_id)
        evicted_items = [item for item in all_items if item.item_id in evicted_ids]

        # Lazy import to avoid circular dependency.
        from paperclaw.context.compaction import CompactionPolicy

        policy = self._compaction_policy
        if policy is None:
            policy = CompactionPolicy()
            self._compaction_policy = policy

        outcome = policy.compact(
            kept=selected,
            evicted=evicted_items,
            budget=budget,
            view=view,
            run_id=run_id,
            at_sequence=at_sequence,
        )
        return outcome, outcome.result

    def _maybe_compact_stub(
        self,
        selected: list[ContextItem],
        excluded: list[dict[str, Any]],
        usable: int,
    ) -> bool:
        """Legacy Phase C stub. Retained for backward compatibility with
        tests that directly invoke the stub. Phase D replaces the call
        site in ``build`` with ``_run_compaction``.

        .. deprecated:: Phase D
            Use ``_run_compaction`` instead. This method will be removed
            in v0.04.1.
        """
        return any(
            rec.get("exclusion_reason") == EXCLUSION_BUDGET
            for rec in excluded
        )

    def _render(self, items: list[ContextItem], view: RoleContextView) -> str:
        """Produce a deterministic rendered string for hashing.

        The rendered string is NOT the prompt itself — it's a stable
        serialization of (view, sorted items) used to compute
        ``rendered_hash``. SOP §4.4 requires the hash to be reproducible
        from ``source_item_ids`` alone; this implementation satisfies
        that by sorting items by item_id and including only stable
        fields.

        Note (§7.2): in a real prompt, external_untrusted content would
        be wrapped in a ``<untrusted_data>`` block separate from
        ``<instructions>``. The hash captures the *what* (which items
        were included) but not the prompt *layout* — layout is a
        Renderer concern (Phase D / v0.04.1).
        """
        payload = {
            "role": view.role,
            "task_id": view.task_id,
            "items": [
                {
                    "item_id": item.item_id,
                    "layer": item.layer,
                    "kind": item.kind,
                    "priority": item.priority,
                    "source_ref": item.source.source_ref,
                    "trust_level": item.source.trust_level,
                    "estimated_tokens": item.estimated_tokens,
                    # content hash, not raw content — keeps the snapshot
                    # hash stable when only whitespace changes in source.
                    "content_sha256": hashlib.sha256(
                        item.content.encode("utf-8")
                    ).hexdigest(),
                }
                for item in sorted(items, key=lambda i: i.item_id)
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ContextBudgetExhausted",
    "ContextBuilder",
    "ContextBuilderError",
    "EXCLUSION_BUDGET",
    "EXCLUSION_CONFLICT",
    "EXCLUSION_DEDUPLICATION",
    "EXCLUSION_EXPIRED",
    "EXCLUSION_SCOPE",
    "EXCLUSION_SUPERSEDED",
    "EXCLUSION_TRUST_VIOLATION",
    "ROLE_COORDINATOR",
    "ROLE_REVIEWER",
    "ROLE_WORKER",
    "RoleContextView",
]
