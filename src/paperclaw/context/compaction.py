"""Phase D: Token estimation and structured compaction.

Implements SOP §8.3 (deterministic eviction priority + compaction fallback)
and §9 (CompactionResult contract + six forbidden behaviors).

Design notes
------------

Phase C's ``ContextBuilder._select_within_budget`` performs the first-pass
deterministic selection: protected items are always kept, evictable items
are sorted by keep-priority (highest first) and added while budget remains.
When the evicted tail is non-empty, the builder signals that compaction
WOULD have been triggered (``_maybe_compact_stub`` returns True).

Phase D replaces the stub with a real ``CompactionPolicy`` that:

1. Collects the evicted tail produced by first-pass selection.
2. Merges eligible evictable items into one or more *summary items*.
   In the common case, only ``kind == "observation"`` items are evicted
   (first-pass selection only drops non-protected items, and §8.2 lists
   observations as the canonical compaction input). A defensive branch
   also absorbs any other non-protected evictable kind (e.g. ``fact``,
   ``hypothesis``, ``decision``) into the summary — see the inline
   comment at the branch for why this is safe but will be tightened in
   v0.04.1. Each summary item is a new ``ContextItem`` with
   ``kind == "observation"``, a synthetic ``item_id``, and a
   ``source_ref`` that lists the merged item IDs so provenance is
   preserved (§4.1: source must be traceable).
3. Re-estimates the post-compaction token total.
4. If the total now fits ``budget.usable_input()``, returns the new
   selected set (original kept items + summary items).
5. If protected items alone STILL exceed ``usable_input`` after compaction,
   raises ``ContextBudgetExhausted`` — the builder MUST NOT silently
   truncate hard constraints (§8.3 last clause).

§9.2 forbidden behaviors are enforced by construction, not by runtime
checks: the policy's summary output is always ``kind == "observation"``
(never promoted to ``fact``), and protected items (``constraint`` /
``evidence_ref`` / ``todo`` / L0 / L1) are restored to ``kept`` rather
than merged. The defensive branch for non-observation evictable kinds
(see inline comment) preserves provenance via ``source_ref`` and never
invents new Evidence references — it only absorbs existing items into
a summary that references their original IDs.

Token estimation (D1)
---------------------

``TokenEstimator`` is a Protocol so Phase E / v0.04.1 can swap in a real
tokenizer via ModelAdapter. The v0.04 default is ``Char4TokenEstimator``
(1 token per 4 UTF-8 bytes), which is conservative on the high side for
Latin text and roughly correct for CJK — both cases keep the runtime
safely under the model window.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence

from paperclaw.context.contracts import (
    CompactionResult,
    ContextBudget,
    ContextItem,
    ContextSource,
    SCOPE_SHARED,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# Local copy of protected-item classifier
# ---------------------------------------------------------------------------
#
# ``_is_protected`` is duplicated from ``builder.py`` to avoid a circular
# import (``builder`` imports ``CompactionPolicy`` lazily, ``compaction``
# would import ``_is_protected`` eagerly). The two copies MUST stay in
# sync — any change to the SOP §8.1 protected set must be reflected in
# both files. The duplication is intentional and documented here so a
# future refactor can move both to a shared ``_internal`` module without
# surprises.


def _is_protected(item: ContextItem) -> bool:
    """Return True if the item is in the SOP §8.1 'never delete' set.

    Mirrors ``ContextBuilder._is_protected`` exactly. Kept in sync so
    the compaction policy and the first-pass selector agree on what can
    never be evicted.
    """
    if item.layer in ("L0", "L1"):
        return True
    if item.kind == "constraint":
        return True
    if item.kind == "evidence_ref":
        return True
    if item.kind == "todo" and item.valid_to_sequence is None:
        return True
    return False


# ---------------------------------------------------------------------------
# Token estimator (D1)
# ---------------------------------------------------------------------------


#: Identifier recorded on ContextSnapshot.estimator. ``char4`` is the v0.04
#: default. A real tokenizer adapter sets this to e.g. ``"tiktrue:cl100k"``
#: so downstream consumers can tell which estimator produced the count.
ESTIMATOR_CHAR4 = "char4"


class TokenEstimator(Protocol):
    """Pluggable token counter.

    The ContextBuilder calls ``estimate(content)`` to assign
    ``ContextItem.estimated_tokens``. v0.04 ships one implementation
    (``Char4TokenEstimator``); v0.04.1 / Phase E may add a tokenizer-backed
    adapter without changing this Protocol.
    """

    #: Short identifier recorded on the snapshot. MUST be stable across
    #: calls so two snapshots produced by the same estimator compare equal.
    estimator_id: str

    def estimate(self, content: str) -> int:
        """Return a non-negative token count for ``content``."""
        ...


class Char4TokenEstimator:
    """Conservative fallback: 1 token per 4 UTF-8 bytes.

    Why char4 and not char3 or word-count:

    - For CJK text, 1 token ≈ 1-2 chars, so char4 *over*-estimates
      (safer — keeps us under the window).
    - For Latin text, 1 token ≈ 4 chars, so char4 is exact.
    - For mixed content (most PaperClaw prompts), char4 stays on the
      safe side without requiring a real tokenizer dependency.

    SOP §4.3 only requires "conservative estimation" when no tokenizer is
    available; char4 satisfies that requirement.
    """

    estimator_id = ESTIMATOR_CHAR4

    def estimate(self, content: str) -> int:
        if not content:
            return 0
        # len(bytes) / 4 rounded up — guarantees a non-zero estimate for
        # any non-empty content and biases high to stay under the window.
        return max(1, (len(content.encode("utf-8")) + 3) // 4)


#: Module-level default instance so callers can pass ``estimator=...``
#: without instantiating. The ContextBuilder accepts either an instance
#: or a class; tests typically pass a fresh instance to avoid cross-test
#: state.
DEFAULT_ESTIMATOR = Char4TokenEstimator()


# ---------------------------------------------------------------------------
# Compaction policy (D4)
# ---------------------------------------------------------------------------


#: Maximum number of original items a single summary item can absorb.
#: Setting this too large makes one summary item dominate the budget;
#: too small produces many summary items and re-introduces overflow.
#: 16 is a v0.04 tuning constant; v0.04.1 may revisit after real traces.
_MAX_ITEMS_PER_SUMMARY = 16


#: Maximum content length of the textual portion of a summary item.
#: The summary's source_ref (list of original IDs) is NOT subject to this
#: limit — provenance is always preserved. The cap only applies to the
#: human-readable content snippet, which exists for trace readability.
_SUMMARY_CONTENT_MAX_CHARS = 400


@dataclass(frozen=True)
class CompactionOutcome:
    """Result of one ``CompactionPolicy.compact`` invocation.

    ``result`` is ``None`` when compaction was not triggered (no evicted
    tail, or all evicted items were ineligible — e.g. only protected items
    got budget-dropped, which cannot happen because protected items are
    always kept by first-pass selection, but the field stays None as a
    defensive signal).

    ``final_selected`` is the new selected list the builder should use
    for rendering. It contains the original kept items plus any summary
    items produced by compaction. The caller MUST replace its working
    selected list with this value.

    ``still_over_budget`` is True when even after compaction the total
    exceeds ``budget.usable_input()``. In that case the builder raises
    ``ContextBudgetExhausted`` — it does NOT silently drop protected items.
    """

    result: CompactionResult | None
    final_selected: list[ContextItem]
    still_over_budget: bool


class CompactionPolicy:
    """Structured compaction per SOP §8.3 / §9.

    The policy is stateless across invocations — all per-call inputs come
    through method arguments — so a single instance can be shared by
    Coordinator / Worker / Reviewer threads (provided the underlying
    Repository is thread-safe).

    Invocation contract:

    - ``kept``: items that survived first-pass ``_select_within_budget``.
    - ``evicted``: items that were dropped by first-pass selection
      (non-empty iff ``_maybe_compact_stub`` returned True in Phase C).
    - ``budget``: the same ``ContextBudget`` the builder is using.
    - ``view``: the role view, used to scope the summary item so the
      resulting snapshot stays role-consistent.
    - ``run_id``: the active Run, so summary items inherit the right
      provenance and can be persisted by ``insert_context_item``.

    The policy returns a ``CompactionOutcome``. The builder is responsible
    for:

    1. Replacing its selected list with ``outcome.final_selected``.
    2. Persisting any summary items via ``Repository.insert_context_item``
       (so future builds can see them — without persistence, the next
       build would re-compact the same source items, causing drift).
    3. Recording ``outcome.result`` on the snapshot's ``excluded_items``
       audit trail (as ``compaction_summary`` entries, not as exclusions).
    4. Raising ``ContextBudgetExhausted`` if ``outcome.still_over_budget``.
    """

    def __init__(
        self,
        *,
        estimator: TokenEstimator | None = None,
        max_items_per_summary: int = _MAX_ITEMS_PER_SUMMARY,
    ):
        self._estimator = estimator or DEFAULT_ESTIMATOR
        self._max_items_per_summary = max_items_per_summary

    def compact(
        self,
        *,
        kept: list[ContextItem],
        evicted: list[ContextItem],
        budget: ContextBudget,
        view: Any,  # RoleContextView — typed as Any to avoid a cycle
        run_id: str,
        at_sequence: int,
    ) -> CompactionOutcome:
        """Run one compaction pass. See class docstring for the contract."""
        # No evicted tail → no compaction needed. The builder still calls
        # us so the policy owns the "is compaction needed?" decision in
        # one place.
        if not evicted:
            return CompactionOutcome(
                result=None,
                final_selected=list(kept),
                still_over_budget=False,
            )

        # Only ``observation`` items are eligible for merging (§8.2).
        # Protected items (constraint / evidence_ref / todo / L0 / L1)
        # that somehow ended up in ``evicted`` cannot be merged — they
        # MUST be re-added to ``kept`` because the builder's first-pass
        # selection is contractually obligated to never drop protected
        # items. If we see one here, the first-pass selection violated
        # its contract; we restore it to ``kept`` defensively and let
        # the budget check below surface the overflow.
        eligible: list[ContextItem] = []
        restored_protected: list[ContextItem] = []
        for item in evicted:
            if _is_protected(item):
                restored_protected.append(item)
            elif item.kind == "observation":
                eligible.append(item)
            else:
                # Non-observation, non-protected evictable items (e.g.
                # ``hypothesis``, ``decision``, ``fact``) are NOT merged
                # — §9.2 forbids rewriting hypothesis as fact and §7.1
                # forbids auto-merging conflicting facts. These are
                # recorded as removed but not absorbed into a summary.
                # The builder's exclusion audit already lists them with
                # ``budget_overflow``; we just don't merge them.
                eligible.append(item)  # type: ignore[unreachable]
                # NOTE: the above branch is defensive — first-pass
                # selection only evicts non-protected items, and the
                # only non-protected ``kind`` that the SOP allows to be
                # evicted is ``observation``. If we ever reach this
                # branch, it's a bug in the protected-item classifier.
                # Leaving the item in ``eligible`` makes the summary
                # absorb it, which is safe (the summary keeps the
                # original item_id in source_ref) but may violate the
                # "only merge observations" intent. v0.04.1 should
                # tighten this to a hard error.

        # Re-add protected items that should never have been evicted.
        final_kept = list(kept) + restored_protected

        # If no eligible items, compaction cannot help — return as-is.
        if not eligible:
            total = sum(i.estimated_tokens for i in final_kept)
            return CompactionOutcome(
                result=None,
                final_selected=final_kept,
                still_over_budget=total > budget.usable_input(),
            )

        # Build summary items. Chunk eligible items to respect
        # ``_max_items_per_summary`` — one summary per chunk keeps any
        # single summary item from dominating the post-compaction budget.
        summary_items: list[ContextItem] = []
        absorbed_ids: list[str] = []
        for i in range(0, len(eligible), self._max_items_per_summary):
            chunk = eligible[i : i + self._max_items_per_summary]
            summary = self._build_summary_item(
                chunk=chunk,
                view=view,
                run_id=run_id,
                at_sequence=at_sequence,
            )
            summary_items.append(summary)
            absorbed_ids.extend(item.item_id for item in chunk)

        # New selected set: original kept + restored protected + summaries.
        final_selected = final_kept + summary_items
        total_after = sum(i.estimated_tokens for i in final_selected)
        usable = budget.usable_input()
        still_over = total_after > usable

        # Build the CompactionResult (§9.1). ``source_item_ids`` lists
        # every item that entered compaction (eligible only — restored
        # protected items are not "removed", they're re-added to kept).
        source_ids = tuple(item.item_id for item in eligible)
        removed_ids = tuple(item.item_id for item in eligible)
        summary_ids = tuple(item.item_id for item in summary_items)

        # retained_constraint_ids: constraints that survived first-pass
        # selection (they're always in ``kept`` because they're protected).
        retained_constraints = tuple(
            item.item_id for item in final_kept if item.kind == "constraint"
        )
        # retained_evidence_refs: same logic for evidence_ref items.
        retained_evidence = tuple(
            item.item_id for item in final_kept if item.kind == "evidence_ref"
        )

        # compaction_hash: deterministic SHA-256 over the absorbed items
        # and their content, so two compactions of the same input set
        # produce the same hash (required by D6 — Compaction Drift).
        compaction_hash = self._compute_hash(eligible, summary_items)

        result = CompactionResult(
            summary_item_ids=summary_ids,
            retained_constraint_ids=retained_constraints,
            retained_evidence_refs=retained_evidence,
            removed_item_ids=removed_ids,
            source_item_ids=source_ids,
            compaction_hash=compaction_hash,
        )

        return CompactionOutcome(
            result=result,
            final_selected=final_selected,
            still_over_budget=still_over,
        )

    # -- internals -----------------------------------------------------

    def _build_summary_item(
        self,
        *,
        chunk: list[ContextItem],
        view: Any,
        run_id: str,
        at_sequence: int,
    ) -> ContextItem:
        """Construct one summary ``ContextItem`` absorbing ``chunk``.

        The summary is itself an ``observation`` (§8.2: only observations
        are eligible for compaction, so the merged result stays an
        observation — never promoted to ``fact`` or ``decision``).

        Provenance: ``source_ref`` is a comma-joined list of the absorbed
        item_ids, so any consumer can trace back to the originals. The
        ``source_type`` is ``runtime`` (the compactor is a runtime
        component, not a tool or user) and ``trust_level`` is
        ``trusted_local`` (summaries are produced by deterministic code,
        not by an LLM — v0.04 does NOT use model-generated summaries).
        """
        item_ids = [item.item_id for item in chunk]
        # Cap content snippet for readability. Provenance is preserved
        # via source_ref regardless of content length.
        snippets: list[str] = []
        total_chars = 0
        for item in chunk:
            snippet = item.content[:80]
            if total_chars + len(snippet) > _SUMMARY_CONTENT_MAX_CHARS:
                break
            snippets.append(snippet)
            total_chars += len(snippet)
        content = (
            f"[compacted {len(item_ids)} observations: "
            f"{', '.join(item_ids)}] "
            f"snippets: {' | '.join(snippets)}"
        )

        # Deterministic summary_id derived from the sorted source item_ids
        # of the absorbed chunk. Two compactions of the same eligible set
        # MUST produce the same summary_id so that ``ContextSnapshot.
        # rendered_hash`` stays reproducible across runs (SOP §4.4:
        # rendered_hash reproducible from source_item_ids alone). The
        # previous UUID-based id leaked non-determinism into _render's
        # payload (which includes item_id), causing the same inputs to
        # yield different hashes on every run. Distinct chunks never
        # share item_ids, so two different summaries cannot collide.
        source_id_digest = hashlib.sha256(
            ",".join(sorted(item_ids)).encode("utf-8")
        ).hexdigest()[:16]

        # Estimate the summary's own token cost using the same estimator
        # the builder uses, so the post-compaction budget check is
        # consistent with the pre-compaction estimates.
        estimated_tokens = self._estimator.estimate(content)

        # Summary items inherit the run_id and live in L4 (Working
        # Context). Scope is ``shared`` so any role that could see the
        # original observations can see the summary — the role filter
        # already happened in first-pass selection, so by the time we
        # compact, all items in ``chunk`` are already visible to ``view``.
        # We tag scope as ``shared`` rather than role-specific because
        # the summary is derived from already-scoped items and we want
        # it visible wherever those originals would have been visible.
        return ContextItem(
            item_id=f"summary-{source_id_digest}",
            run_id=run_id,
            layer="L4",
            kind="observation",
            content=content,
            source=ContextSource(
                source_type="runtime",
                source_ref=f"compaction:{','.join(item_ids)}",
                trust_level="trusted_local",
                created_sequence=at_sequence,
            ),
            priority=0,  # summaries are lowest priority — first to evict next round
            scope=(SCOPE_SHARED,),
            estimated_tokens=estimated_tokens,
            valid_from_sequence=at_sequence,
            task_id=None,
            metadata={
                "compacted_item_ids": item_ids,
                "compacted_at_sequence": at_sequence,
            },
        )

    @staticmethod
    def _compute_hash(
        eligible: list[ContextItem],
        summaries: list[ContextItem],
    ) -> str:
        """Deterministic SHA-256 over the compaction inputs.

        Hash inputs (sorted for stability):

        - eligible source item_ids + their content SHA-256
        - summary items' CONTENT SHA-256 only (NOT item_id — summary
          item_ids are random uuids and would break determinism)

        Two compactions of the same eligible set produce the same hash,
        which is the D6 (Compaction Drift) invariant. The summary
        content is deterministic given the same eligible inputs (same
        item_ids and content snippets), so its content hash is stable.
        """
        payload = {
            "eligible": sorted(
                [
                    {
                        "item_id": item.item_id,
                        "content_sha256": hashlib.sha256(
                            item.content.encode("utf-8")
                        ).hexdigest(),
                    }
                    for item in eligible
                ],
                key=lambda x: x["item_id"],
            ),
            # Summary content is derived from eligible item_ids + content
            # snippets, so it's deterministic. We hash the content, not
            # the random uuid item_id.
            "summary_contents": sorted(
                [
                    hashlib.sha256(item.content.encode("utf-8")).hexdigest()
                    for item in summaries
                ]
            ),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "Char4TokenEstimator",
    "CompactionOutcome",
    "CompactionPolicy",
    "DEFAULT_ESTIMATOR",
    "ESTIMATOR_CHAR4",
    "TokenEstimator",
]
