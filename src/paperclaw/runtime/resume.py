"""Safe-resume decision logic for Addendum P0-C §5.3.

``evaluate_resume_safety`` inspects a Checkpoint against the current
NodeRegistry and the runtime's pending-operation / file-snapshot state, then
returns a ``ResumeDecision`` that tells the caller whether to:

- ``ok``: auto-resume from ``checkpoint.next_node_id``.
- ``recovery_required``: STOP. A node or mutating operation is in a
  non-terminal state. A human or higher-level recovery process must reconcile
  the partial state before re-entering the Flow. NEVER auto-replay a
  mutating operation (Addendum §5.3).
- ``incompatible_flow_definition``: STOP. The Flow definition has changed
  since the Checkpoint was written (registry hash mismatch or
  ``next_node_id`` no longer exists). Silently mapping to the "closest"
  node name is explicitly forbidden (Addendum §5.4).

Design intent — why a pure function instead of a method on Checkpoint:

1. The decision depends on inputs the Checkpoint does not own: the current
   NodeRegistry (which may have been rebuilt in a new process) and the
   live file-snapshot verifier (which reads the filesystem NOW). Putting
   this logic on Checkpoint would force Checkpoint to hold a registry
   reference, breaking its frozen-dataclass purity.
2. A pure function is trivially testable: synthesize a Checkpoint, a
   registry, and a pending_operations list, assert the decision. No I/O,
   no DB, no fixtures required for the core logic.
3. The caller (InstrumentedFlowRunner or a higher-level recovery shell)
   owns the policy of WHAT to do with a ``recovery_required`` decision —
   the function only computes the decision, it does not trigger recovery.

Pending-operation state vocabulary (Addendum §5.3):

- ``"started"`` (or any non-terminal state) → the operation is in flight.
  Resume MUST NOT proceed because the operation's side effects are
  unknown. The caller must inspect the operation, determine whether it
  committed or rolled back, and update its state to a terminal value
  before re-evaluating.
- ``"committed"``, ``"failed"``, ``"unknown_outcome"`` → terminal. The
  operation's side effects are known (or explicitly marked unknown). Resume
  MAY proceed if no other blocker exists.

File-snapshot verification:

- ``file_snapshot_verifier`` is optional. When ``None``, file snapshots
  are NOT checked — the caller asserts that no file-state changes are
  possible (e.g. the process never exited). When provided, it MUST return
  ``True`` for a snapshot that still matches the filesystem and ``False``
  for a mismatch. A mismatch means an external process (or the crashed
  run itself) modified the file after the Checkpoint was written; resume
  MUST stop because the Checkpoint's view of file state is stale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from paperclaw.context.contracts import Checkpoint
from paperclaw.runtime.error_codes import (
    INCOMPATIBLE_FLOW_DEFINITION,
    RECOVERY_REQUIRED,
)

if TYPE_CHECKING:
    from paperclaw.runtime.node_registry import NodeRegistry


#: Operation states that mark a pending operation as safely resolved. Any
#: other state (notably ``"started"``) means the operation is in flight and
#: resume MUST stop. The set is intentionally small — callers that need richer
#: state machines (e.g. ``"rolling_back"``) MUST map them to one of these
#: terminal values before calling ``evaluate_resume_safety``, because
#: ``evaluate_resume_safety`` treats unknown states as non-terminal (the
#: safe default is "do not resume").
TERMINAL_OPERATION_STATES: frozenset[str] = frozenset(
    {"committed", "failed", "unknown_outcome"}
)


@dataclass(frozen=True)
class ResumeDecision:
    """Result of ``evaluate_resume_safety``.

    The decision is the ONLY field the caller MUST read. The remaining
    fields are diagnostic context surfaced so a recovery shell can render a
    useful error message without re-deriving the inputs.

    Fields:

    - ``can_auto_resume``: ``True`` only when ``status == "ok"``. Convenience
      for callers that do not care about the distinction between
      ``recovery_required`` and ``incompatible_flow_definition``.
    - ``status``: one of ``"ok"``, ``"recovery_required"``,
      ``"incompatible_flow_definition"``.
    - ``reason``: human-readable explanation of the decision. Stable across
      runs for the same inputs (no timestamps, no object ids) so tests can
      assert on substrings.
    - ``last_safe_sequence``: the Checkpoint's ``last_committed_sequence``.
      The caller should reject any event with a lower sequence than this
      when resuming (Addendum §4.4: event ordering MUST NOT rely on
      timestamp alone).
    - ``next_node_id``: the node the runner should enter on resume. Mirrors
      ``checkpoint.next_node_id``. ``None`` when the Checkpoint has no
      ``next_node_id`` (legacy v2 Checkpoint or terminal state).
    - ``pending_operations``: the pending operations list as evaluated
      (echoed for traceability — the caller already has this input, but
      including it in the decision makes the decision self-contained for
      logging).
    - ``file_conflicts``: file snapshots that failed verification. Empty
      when no verifier was supplied or all snapshots matched.
    - ``current_registry_hash`` / ``checkpoint_registry_hash``: the two
      hashes being compared. Surfaced so a recovery shell can report
      "stored=X current=Y" without re-reading the registry.
    - ``recommended_action``: short machine-readable hint for the caller.
      ``"resume_from_next_node"`` for ``ok``; ``"initiate_recovery"`` for
      ``recovery_required``; ``"refuse_resume_flow_definition_changed"``
      for ``incompatible_flow_definition``.
    """

    can_auto_resume: bool
    status: str
    reason: str
    last_safe_sequence: int
    next_node_id: str | None
    pending_operations: list[dict[str, Any]] = field(default_factory=list)
    file_conflicts: list[dict[str, Any]] = field(default_factory=list)
    current_registry_hash: str | None = None
    checkpoint_registry_hash: str | None = None
    recommended_action: str = "refuse_resume"


def evaluate_resume_safety(
    *,
    checkpoint: Checkpoint,
    current_registry: "NodeRegistry",
    pending_operations: list[dict[str, Any]] | None = None,
    file_snapshot_verifier: Callable[[dict[str, Any]], bool] | None = None,
) -> ResumeDecision:
    """Decide whether the runtime can auto-resume from ``checkpoint``.

    Implements Addendum §5.3 rules in the order that minimizes wasted work
    and gives the most actionable error first:

    1. **Registry membership.** If ``checkpoint.next_node_id`` is not in
       ``current_registry``, the Flow definition has changed (or the
       Checkpoint is from a different Flow). Return
       ``incompatible_flow_definition``. This is checked BEFORE the hash
       because a missing node is a clearer signal than a hash mismatch —
       the hash would also mismatch, but the operator can act on "node X
       was removed" faster than "hash differs".
    2. **Registry hash.** If ``checkpoint.checkpoint_registry_hash`` is set
       and differs from ``current_registry.registry_hash``, the Flow
       definition has changed in a way that added/removed/renamed nodes
       even though ``next_node_id`` still exists. Return
       ``incompatible_flow_definition``. A ``None`` checkpoint hash is
       treated as "not checked" — legacy v2 Checkpoints did not record the
       hash, and v0.04 does not retroactively block them (the membership
       check above is the primary guard).
    3. **Pending operations.** If any operation in ``pending_operations``
       has a non-terminal ``state`` (anything not in
       ``TERMINAL_OPERATION_STATES``), the operation is in flight. Return
       ``recovery_required``. NEVER auto-replay a mutating operation.
    4. **File snapshots.** If ``file_snapshot_verifier`` is provided and
       returns ``False`` for any snapshot, the filesystem state has
       diverged from the Checkpoint. Return ``recovery_required``.
    5. **Otherwise ``ok``.** Resume from ``checkpoint.next_node_id``.

    Args:
        checkpoint: The Checkpoint to evaluate. Reads
            ``next_node_id``, ``checkpoint_registry_hash``, and
            ``last_committed_sequence``.
        current_registry: The runtime's current NodeRegistry. Used for
            membership and hash comparison.
        pending_operations: Current pending operations, typically
            reconstructed from the event log (which may be newer than the
            Checkpoint's own ``pending_operations`` field). Pass ``None``
            or an empty list if no operations are in flight.
        file_snapshot_verifier: Optional callable that returns ``True`` if
            a file snapshot dict still matches the filesystem. ``None``
            disables file-snapshot checking (the caller asserts no file
            state changes are possible).

    Returns:
        A ``ResumeDecision``. The caller MUST inspect ``can_auto_resume``
        (or ``status``) before resuming; the other fields are diagnostic.
    """
    ops = list(pending_operations) if pending_operations is not None else []
    current_hash = current_registry.registry_hash
    stored_hash = checkpoint.checkpoint_registry_hash
    next_node_id = checkpoint.next_node_id

    # ------------------------------------------------------------------
    # Rule 1: next_node_id must exist in the current registry.
    # ------------------------------------------------------------------
    # A missing next_node_id means either (a) the Flow definition removed
    # the node, or (b) the Checkpoint is from a different Flow entirely.
    # Either way, resume MUST stop — silently mapping to a similarly-named
    # node would hide a real definition change (Addendum §5.4).
    if next_node_id is None or next_node_id not in current_registry:
        return ResumeDecision(
            can_auto_resume=False,
            status="incompatible_flow_definition",
            reason=(
                f"next_node_id {next_node_id!r} is not present in the current "
                f"NodeRegistry; the Flow definition has changed or the "
                f"Checkpoint belongs to a different Flow"
            ),
            last_safe_sequence=checkpoint.last_committed_sequence,
            next_node_id=next_node_id,
            pending_operations=ops,
            current_registry_hash=current_hash,
            checkpoint_registry_hash=stored_hash,
            recommended_action="refuse_resume_flow_definition_changed",
        )

    # ------------------------------------------------------------------
    # Rule 2: registry hash must match (when the Checkpoint recorded one).
    # ------------------------------------------------------------------
    # A None stored_hash means the Checkpoint predates P0-C (v2 schema).
    # v0.04 does not retroactively block legacy Checkpoints; the membership
    # check above is the primary guard. Future versions may tighten this to
    # require a hash on every Checkpoint.
    if stored_hash is not None and stored_hash != current_hash:
        return ResumeDecision(
            can_auto_resume=False,
            status="incompatible_flow_definition",
            reason=(
                f"node registry hash mismatch: stored={stored_hash} "
                f"current={current_hash}; the Flow definition has changed "
                f"since the Checkpoint was written"
            ),
            last_safe_sequence=checkpoint.last_committed_sequence,
            next_node_id=next_node_id,
            pending_operations=ops,
            current_registry_hash=current_hash,
            checkpoint_registry_hash=stored_hash,
            recommended_action="refuse_resume_flow_definition_changed",
        )

    # ------------------------------------------------------------------
    # Rule 3: no pending operation may be in a non-terminal state.
    # ------------------------------------------------------------------
    # An operation with state="started" (or any state not in
    # TERMINAL_OPERATION_STATES) means the operation's side effects are
    # unknown. Auto-replaying would risk double-application (e.g. a file
    # write that actually committed but the confirmation event was lost).
    # Addendum §5.3: "NEVER auto-replay a mutating operation."
    non_terminal = [
        op for op in ops
        if op.get("state") not in TERMINAL_OPERATION_STATES
    ]
    if non_terminal:
        return ResumeDecision(
            can_auto_resume=False,
            status="recovery_required",
            reason=(
                f"{len(non_terminal)} pending operation(s) are in a "
                f"non-terminal state (started but not committed/failed/"
                f"unknown_outcome); manual reconciliation required before "
                f"resume"
            ),
            last_safe_sequence=checkpoint.last_committed_sequence,
            next_node_id=next_node_id,
            pending_operations=ops,
            current_registry_hash=current_hash,
            checkpoint_registry_hash=stored_hash,
            recommended_action="initiate_recovery",
        )

    # ------------------------------------------------------------------
    # Rule 4: file snapshots must still match (when a verifier is given).
    # ------------------------------------------------------------------
    # The verifier reads the filesystem NOW and compares against the
    # snapshot's recorded hash. A mismatch means an external process (or
    # the crashed run itself) modified the file after the Checkpoint was
    # written. Resume MUST stop because the Checkpoint's view of file
    # state is stale — re-running the node might overwrite unsaved changes.
    conflicts: list[dict[str, Any]] = []
    if file_snapshot_verifier is not None:
        for snap in checkpoint.file_snapshots:
            if not file_snapshot_verifier(snap):
                conflicts.append(snap)
    if conflicts:
        return ResumeDecision(
            can_auto_resume=False,
            status="recovery_required",
            reason=(
                f"{len(conflicts)} file snapshot(s) no longer match the "
                f"filesystem; the file state has diverged from the "
                f"Checkpoint"
            ),
            last_safe_sequence=checkpoint.last_committed_sequence,
            next_node_id=next_node_id,
            pending_operations=ops,
            file_conflicts=conflicts,
            current_registry_hash=current_hash,
            checkpoint_registry_hash=stored_hash,
            recommended_action="initiate_recovery",
        )

    # ------------------------------------------------------------------
    # All checks passed: safe to resume from next_node_id.
    # ------------------------------------------------------------------
    return ResumeDecision(
        can_auto_resume=True,
        status="ok",
        reason=(
            f"checkpoint is safe to resume from next_node_id={next_node_id!r}; "
            f"registry hash matches and no pending operations are in flight"
        ),
        last_safe_sequence=checkpoint.last_committed_sequence,
        next_node_id=next_node_id,
        pending_operations=ops,
        current_registry_hash=current_hash,
        checkpoint_registry_hash=stored_hash,
        recommended_action="resume_from_next_node",
    )
