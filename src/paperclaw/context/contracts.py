"""Frozen data contracts for the v0.04 Context Runtime.

All inter-agent context is exchanged via immutable dataclasses with explicit
provenance, trust level, scope, and lifecycle metadata. Free-form model text
never directly becomes a ContextItem; the Runtime must explicitly construct
items with a verifiable ContextSource.

Reference: Plan/drafts/PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md §4.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Trust / layer / kind constants
# ---------------------------------------------------------------------------

#: Allowed values for ContextSource.trust_level. Lower index = higher trust.
#: ``external_untrusted`` MUST NOT enter L0/L1 (Runtime Constitution / Role).
TRUST_LEVELS = (
    "system",
    "trusted_local",
    "user",
    "tool_output",
    "external_untrusted",
)

#: Allowed values for ContextSource.source_type.
SOURCE_TYPES = (
    "user",
    "runtime",
    "file",
    "tool",
    "worker_result",
    "evidence",
    "external",
)

#: Allowed values for ContextItem.layer (six-layer context model).
CONTEXT_LAYERS = ("L0", "L1", "L2", "L3", "L4", "L5")

#: Allowed values for ContextItem.kind.
CONTEXT_KINDS = (
    "fact",
    "decision",
    "hypothesis",
    "todo",
    "constraint",
    "evidence_ref",
    "observation",
)

#: Scope markers used by ContextItem.scope. ``shared`` is visible to every role;
#: ``worker:<task_id>`` restricts visibility to the owner of that task.
SCOPE_COORDINATOR = "coordinator"
SCOPE_REVIEWER = "reviewer"
SCOPE_SHARED = "shared"


# ---------------------------------------------------------------------------
# ContextSource (§4.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextSource:
    """Provenance of a ContextItem.

    Every piece of context must be traceable. ``trust_level`` drives prompt
    injection boundaries: ``external_untrusted`` content is rendered as a data
    block and cannot reach L0/L1.
    """

    source_type: str
    source_ref: str
    trust_level: str
    created_sequence: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# ContextItem (§4.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextItem:
    """One structured, immutable piece of context.

    Hard constraints (enforced by ContextBuilder, not by the dataclass itself):

    - ``fact`` must originate from user, deterministic tool output, or existing
      Evidence. Model-generated content does NOT auto-promote to ``fact``.
    - ``hypothesis`` cannot become ``fact`` after compaction.
    - ``supersedes_item_id`` only invalidates the prior item; it does not delete
      the original record.
    - Original Evidence is never overwritten by ContextItem content.
    """

    item_id: str
    run_id: str
    layer: str
    kind: str
    content: str
    source: ContextSource
    priority: int
    scope: tuple[str, ...]
    estimated_tokens: int
    valid_from_sequence: int
    task_id: str | None = None
    valid_to_sequence: int | None = None
    supersedes_item_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # tuples serialize as JSON arrays; keep scope as list for storage.
        data["scope"] = list(self.scope)
        data["source"] = self.source.to_dict()
        return data

    def is_active_at(self, sequence: int) -> bool:
        """Return True if this item is effective at ``sequence``.

        Effective window is ``[valid_from_sequence, valid_to_sequence)``.
        ``valid_to_sequence is None`` means open-ended (still active).
        """
        if sequence < self.valid_from_sequence:
            return False
        if self.valid_to_sequence is not None and sequence >= self.valid_to_sequence:
            return False
        return True


# ---------------------------------------------------------------------------
# ContextBudget (§4.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextBudget:
    """Token budget for one ContextBuilder invocation.

    The effective usable input budget is::

        usable_input = max_input_tokens
                      - reserved_output_tokens
                      - safety_margin_tokens

    ``safety_margin_tokens`` MUST be at least 10% of the model window. When no
    tokenizer is available, ModelAdapter falls back to a conservative estimator
    and records the estimator type in the resulting ContextSnapshot.
    """

    max_input_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    max_single_item_tokens: int
    max_tool_output_tokens: int

    def usable_input(self) -> int:
        """Return the effective input token budget after reserves."""
        return max(
            0,
            self.max_input_tokens
            - self.reserved_output_tokens
            - self.safety_margin_tokens,
        )

    def validate(self) -> None:
        """Enforce invariants. Raises ValueError on violation."""
        if self.max_input_tokens <= 0:
            raise ValueError("max_input_tokens must be positive")
        if self.reserved_output_tokens < 0:
            raise ValueError("reserved_output_tokens must be non-negative")
        if self.safety_margin_tokens < 0:
            raise ValueError("safety_margin_tokens must be non-negative")
        # SOP §4.3: safety margin must be >= 10% of model window.
        if self.safety_margin_tokens * 10 < self.max_input_tokens:
            raise ValueError(
                "safety_margin_tokens must be >= 10% of max_input_tokens"
            )
        if self.usable_input() <= 0:
            raise ValueError(
                "usable_input budget is non-positive after reserves"
            )
        if self.max_single_item_tokens <= 0:
            raise ValueError("max_single_item_tokens must be positive")
        if self.max_tool_output_tokens <= 0:
            raise ValueError("max_tool_output_tokens must be positive")


# ---------------------------------------------------------------------------
# SessionEvent (§4.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionEvent:
    """Append-only event in a Run's monotonic event log.

    Rules (enforced by Repository):

    - ``sequence`` is strictly monotonic within a single Run.
    - Duplicate ``event_id`` must be idempotently rejected or return the
      existing record.
    - ``payload`` must carry a ``schema_version`` field.
    - Ordering MUST NOT rely on ``created_at`` alone; ``sequence`` is the
      authoritative order.
    """

    event_id: str
    conversation_id: str
    run_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# ContextSnapshot (§4.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextSnapshot:
    """Immutable record of what one model call actually saw.

    A Snapshot is NOT a recovery point. It records which ContextItems entered
    the prompt, which were excluded and why, the rendered hash, and the token
    estimator used. The rendered string can be exported but is not the sole
    source of truth; ``source_item_ids`` is.
    """

    snapshot_id: str
    run_id: str
    agent_id: str
    role: str
    source_item_ids: tuple[str, ...]
    excluded_items: tuple[dict[str, Any], ...]
    rendered_hash: str
    estimated_tokens: int
    estimator: str
    created_sequence: int
    task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_item_ids"] = list(self.source_item_ids)
        data["excluded_items"] = list(self.excluded_items)
        return data


# ---------------------------------------------------------------------------
# Checkpoint (§4.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Checkpoint:
    """A safe step-boundary state marker for resume decisions.

    A Checkpoint lets the Runtime answer:

    - which event sequence to resume from,
    - whether pending side effects exist,
    - the current Task / budget state,
    - whether key files still match the checkpoint,
    - whether auto-resume is allowed or ``recovery_required`` must be raised.

    A Checkpoint never overwrites original Evidence; it is a recovery decision
    record, not a state replacement.
    """

    checkpoint_id: str
    run_id: str
    last_committed_sequence: int
    task_state_revision: int
    budget_state: dict[str, Any]
    pending_operations: tuple[dict[str, Any], ...]
    file_snapshots: tuple[dict[str, Any], ...]
    state_hash: str
    schema_version: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pending_operations"] = list(self.pending_operations)
        data["file_snapshots"] = list(self.file_snapshots)
        return data


# ---------------------------------------------------------------------------
# CompactionResult (§9.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompactionResult:
    """Structured output of one compaction pass.

    Forbidden behaviors (enforced by tests, not by the dataclass):

    - MUST NOT rewrite ``hypothesis`` items as ``fact``.
    - MUST NOT fabricate Evidence refs.
    - MUST NOT drop unresolved blockers or user hard constraints.
    - MUST NOT overwrite original sources.
    - MUST NOT promote external data to Runtime instructions.
    """

    summary_item_ids: tuple[str, ...]
    retained_constraint_ids: tuple[str, ...]
    retained_evidence_refs: tuple[str, ...]
    removed_item_ids: tuple[str, ...]
    source_item_ids: tuple[str, ...]
    compaction_hash: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["summary_item_ids"] = list(self.summary_item_ids)
        data["retained_constraint_ids"] = list(self.retained_constraint_ids)
        data["retained_evidence_refs"] = list(self.retained_evidence_refs)
        data["removed_item_ids"] = list(self.removed_item_ids)
        data["source_item_ids"] = list(self.source_item_ids)
        return data


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Centralized so tests can monkeypatch and so all events use the same format.
    """
    return datetime.now(timezone.utc).isoformat()


def validate_source(source: ContextSource) -> None:
    """Validate that a ContextSource fields are within the allowed vocabularies."""
    if source.source_type not in SOURCE_TYPES:
        raise ValueError(
            f"invalid source_type {source.source_type!r}; "
            f"expected one of {SOURCE_TYPES}"
        )
    if source.trust_level not in TRUST_LEVELS:
        raise ValueError(
            f"invalid trust_level {source.trust_level!r}; "
            f"expected one of {TRUST_LEVELS}"
        )
    if source.created_sequence < 0:
        raise ValueError("created_sequence must be non-negative")


def validate_item(item: ContextItem) -> None:
    """Validate layer / kind / scope invariants on a ContextItem."""
    if item.layer not in CONTEXT_LAYERS:
        raise ValueError(
            f"invalid layer {item.layer!r}; expected one of {CONTEXT_LAYERS}"
        )
    if item.kind not in CONTEXT_KINDS:
        raise ValueError(
            f"invalid kind {item.kind!r}; expected one of {CONTEXT_KINDS}"
        )
    validate_source(item.source)
    if item.valid_from_sequence < 0:
        raise ValueError("valid_from_sequence must be non-negative")
    if (
        item.valid_to_sequence is not None
        and item.valid_to_sequence <= item.valid_from_sequence
    ):
        raise ValueError(
            "valid_to_sequence must be strictly greater than valid_from_sequence"
        )
    if item.estimated_tokens < 0:
        raise ValueError("estimated_tokens must be non-negative")
    if not item.scope:
        raise ValueError("scope must be non-empty")


def validate_event(event: SessionEvent) -> None:
    """Validate SessionEvent invariants before persistence."""
    if event.sequence < 0:
        raise ValueError("sequence must be non-negative")
    if "schema_version" not in event.payload:
        raise ValueError("payload must carry schema_version")
    if not event.event_type:
        raise ValueError("event_type must be non-empty")
