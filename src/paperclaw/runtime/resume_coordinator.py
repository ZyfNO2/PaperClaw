"""ResumeCoordinator: end-to-end safe resume entry point (Phase E).

This module wires the P0-C decision primitive (``evaluate_resume_safety``)
to the SessionService read-side (``latest_checkpoint``, ``list_events``,
``list_task_states``) and the Phase E ``FileSnapshotVerifier`` so a caller
can decide whether to auto-resume a crashed or stopped run with one call.

SOP §10 boundary compliance:

- §10.1 "auto-allow resume" (7 conditions) maps to:

  1. "存在已提交 Checkpoint"        → ``latest_checkpoint() is not None``
  2. "last_committed_sequence 可读" → ``Checkpoint.last_committed_sequence``
  3. "无 pending mutating operation"→ ``build_pending_operations`` finds
     no non-terminal ops (delegated to ``evaluate_resume_safety`` Rule 3)
  4. "TaskState revision 一致"       → not enforced here; the caller is
     expected to have committed the TaskState before the Checkpoint.
     v0.04 does not auto-reconcile revisions (deferred to v0.04.1).
  5. "关键文件 hash 重新验证"        → ``FileSnapshotVerifier.verify``
  6. "schema version 兼容"          → ``Checkpoint.schema_version == 1``
     (checked here as a hard gate — a future v2 schema would require a
     migration step the coordinator does not yet implement).
  7. "预算状态合法"                 → v0.04 does not persist budget
     state in the Checkpoint (``budget_state={}``); this condition is
     treated as "trivially satisfied" until Phase F wires real budget
     tracking.

- §10.2 "must stop" (8 conditions) is the negation and maps to the
  reverse of each rule above plus the §10.2 "恢复将导致副作用重放"
  guard (``RECOVERY_REQUIRED``).

- §10.3 "v0.04 does NOT promise" is enforced by *omission*: the
  coordinator never calls a mutating tool, never tries to restore a
  process tree, and never re-enters an active Worker. It only computes
  the decision; the caller owns the recovery policy.

Design decision — why a separate class instead of extending SessionService:

1. ``SessionService`` is a Runtime-facing manager (emit / update_task_state
   / close). Mixing resume-decision logic into it would couple the
   write-side and read-side of the session and force every caller to
   carry resume dependencies (NodeRegistry, FileSnapshotVerifier) even
   when they only want to emit events.

2. ``ResumeCoordinator`` is a *pure* decision layer: it reads from the
   SessionService and the NodeRegistry, but writes nothing. This makes
   it trivially testable with a real SQLite-backed SessionService and a
   synthetic registry, without fixtures for the write path.

3. The coordinator composes ``evaluate_resume_safety`` rather than
   duplicating its rules. The P0-C primitive stays the source of truth
   for "given these inputs, what is the decision?"; the coordinator
   only gathers the inputs.

``build_pending_operations`` helper (Phase E-2):

The helper reconstructs the pending-operations list from the SessionEvent
log. It is exported separately so a recovery shell can inspect the same
list the coordinator used, without re-deriving it from events.

Events scanned (Addendum §5.3 pending-operation vocabulary):

- ``operation.started``         → marks an operation as in-flight.
- ``operation.committed``       → terminal: side effects known applied.
- ``operation.failed``          → terminal: side effects known absent.
- ``operation.unknown_outcome`` → terminal: side effects unknown but the
  operation has been observed to a terminal state (caller asserted it).

An operation is "pending non-terminal" when it has ``operation.started``
but no matching terminal event. ``evaluate_resume_safety`` treats any
non-terminal state as a blocker (Addendum §5.3: NEVER auto-replay).

The helper pairs events by ``operation_id``. When multiple ``started``
events exist for the same id (e.g. a retry), the LATEST one wins; this
matches the idempotency ledger's "last write wins" semantics. When
multiple terminal events exist, the latest terminal state wins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from paperclaw.context.contracts import SessionEvent
from paperclaw.runtime.error_codes import RECOVERY_REQUIRED
from paperclaw.runtime.resume import ResumeDecision, evaluate_resume_safety

if TYPE_CHECKING:
    from paperclaw.context.session import SessionService
    from paperclaw.runtime.file_snapshot import FileSnapshotVerifier
    from paperclaw.runtime.node_registry import NodeRegistry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: SOP §10.1 schema version gate. A Checkpoint with a higher schema
#: version requires a migration step the coordinator does not yet
#: implement; resume MUST stop rather than guessing how to read the
#: new schema.
SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})

#: Event types that mark an operation as STARTED. Anything not in the
#: terminal set below is treated as non-terminal by
#: ``evaluate_resume_safety`` (safe default: do not resume).
OPERATION_STARTED_EVENT = "operation.started"

#: Event types that mark an operation as TERMINAL. The state value is
#: what gets recorded in ``pending_operations[i]["state"]``.
OPERATION_TERMINAL_EVENTS: dict[str, str] = {
    "operation.committed": "committed",
    "operation.failed": "failed",
    "operation.unknown_outcome": "unknown_outcome",
}

#: TaskState statuses that mark a Worker as still in-flight. SOP §10.2:
#: "MultiAgent Worker 在崩溃时仍标记 active" → must stop. v0.04 only
#: DETECTS this condition; it does not attempt to recover the Worker
#: (SOP §10.3 explicitly defers active Worker recovery).
ACTIVE_TASK_STATUSES: frozenset[str] = frozenset({"active", "running", "started"})


# ---------------------------------------------------------------------------
# build_pending_operations: reconstruct from event log
# ---------------------------------------------------------------------------


def build_pending_operations(events: list[SessionEvent]) -> list[dict[str, Any]]:
    """Reconstruct the pending-operations list from SessionEvents.

    Scans ``events`` for ``operation.started`` / ``operation.committed``
    / ``operation.failed`` / ``operation.unknown_outcome`` and pairs
    them by ``operation_id``. Returns one entry per operation_id,
    carrying the latest known state.

    Args:
        events: Events emitted after the Checkpoint's
            ``last_committed_sequence``. The caller is responsible for
            scoping the list (typically
            ``session.list_events(since_sequence=cp.last_committed_sequence)``).
            Events at or before the sequence are not relevant because
            the Checkpoint already captured their state.

    Returns:
        list of pending operations, each a dict with at least:

        - ``operation_id`` (str)
        - ``state`` (str): one of ``"started"``, ``"committed"``,
          ``"failed"``, ``"unknown_outcome"``.
        - ``event_type`` (str): the event that produced this state.
        - ``started_at`` (str | None): ISO timestamp from the
          ``operation.started`` payload's ``created_at``.

        Terminal entries additionally carry ``terminal_at``.

    The list order is stable: operations are returned in the order their
    ``operation.started`` event was first seen. This makes the output
    deterministic across runs for the same event log (tests can assert
    on ordering).
    """
    # Map operation_id → latest known state entry.
    # Use dict to deduplicate; iteration order is insertion order (Python
    # 3.7+), which gives us the stable "order of first started event"
    # ordering documented above.
    operations: dict[str, dict[str, Any]] = {}

    for ev in events:
        op_id = ev.payload.get("operation_id")
        if not isinstance(op_id, str) or not op_id:
            # Malformed event (no operation_id). Skip rather than crash —
            # the event log is the source of truth and we cannot invent
            # an operation_id. A separate audit should flag these.
            continue

        if ev.event_type == OPERATION_STARTED_EVENT:
            # First started event for this op establishes the entry.
            # Subsequent started events (retries) UPDATE the entry but
            # preserve the original started_at (so the operator can see
            # how long the operation has been in flight).
            entry = operations.get(op_id)
            if entry is None:
                operations[op_id] = {
                    "operation_id": op_id,
                    "state": "started",
                    "event_type": ev.event_type,
                    "started_at": ev.created_at,
                }
            else:
                # Retry / re-start: keep the original started_at, but
                # mark the state as "started" again (the previous
                # terminal state, if any, is superseded).
                entry["state"] = "started"
                entry["event_type"] = ev.event_type
                entry.setdefault("started_at", ev.created_at)

        elif ev.event_type in OPERATION_TERMINAL_EVENTS:
            entry = operations.get(op_id)
            if entry is None:
                # Terminal event without a matching started event.
                # This is unusual but not impossible (event log
                # truncation, partial migration). Record a synthetic
                # entry with no started_at so the operator can see it.
                operations[op_id] = {
                    "operation_id": op_id,
                    "state": OPERATION_TERMINAL_EVENTS[ev.event_type],
                    "event_type": ev.event_type,
                    "started_at": None,
                    "terminal_at": ev.created_at,
                }
            else:
                entry["state"] = OPERATION_TERMINAL_EVENTS[ev.event_type]
                entry["event_type"] = ev.event_type
                entry["terminal_at"] = ev.created_at

    return list(operations.values())


# ---------------------------------------------------------------------------
# ResumeCoordinator: end-to-end decision entry point
# ---------------------------------------------------------------------------


class ResumeCoordinator:
    """Decide whether the runtime can auto-resume a stopped run.

    Composes ``SessionService`` read-side + ``NodeRegistry`` +
    ``FileSnapshotVerifier`` + ``build_pending_operations`` into a
    single ``decide_resume`` call.

    Usage (typical resume flow)::

        repo, session = reopen_session(db_path,
                                        conversation_id="conv-1",
                                        run_id="run-xyz")
        coordinator = ResumeCoordinator(registry=current_registry,
                                          file_verifier=FileSnapshotVerifier())
        decision = coordinator.decide_resume(session)
        if decision.can_auto_resume:
            resume_point = FlowResumePoint(
                run_id=session.run_id,
                completed_node_id=decision.next_node_id,
                ...
            )
            runner.run(flow, shared, services=services, resume_point=resume_point)
        else:
            # surface decision.recommended_action + decision.reason
            ...

    The coordinator NEVER calls a mutating tool, NEVER re-enters a node,
    NEVER tries to restore a process tree. It only computes the decision
    (SOP §10.3: v0.04 does NOT promise automatic recovery of active
    Workers, FileLeases, or in-flight side effects).
    """

    def __init__(
        self,
        *,
        registry: "NodeRegistry",
        file_verifier: "FileSnapshotVerifier | None" = None,
    ):
        self._registry = registry
        self._file_verifier = file_verifier

    @property
    def registry(self) -> "NodeRegistry":
        return self._registry

    @property
    def file_verifier(self) -> "FileSnapshotVerifier | None":
        return self._file_verifier

    def decide_resume(
        self,
        session: "SessionService",
        *,
        pending_operations: list[dict[str, Any]] | None = None,
    ) -> ResumeDecision:
        """Decide whether the runtime can auto-resume ``session.run_id``.

        Args:
            session: A reopened SessionService bound to the run that
                may be resumed. The session is NOT modified by this
                call (read-only).
            pending_operations: Optional pre-computed pending
                operations list. When ``None`` (default), the
                coordinator reconstructs the list from
                ``session.list_events(since_sequence=...)``. Callers
                that already have the list (e.g. from a prior
                ``build_pending_operations`` call) can pass it to avoid
                a second scan.

        Returns:
            A ``ResumeDecision``. The caller MUST inspect
            ``can_auto_resume`` (or ``status``) before resuming.

        The decision is the ONLY authoritative output. Diagnostic
        fields (``pending_operations``, ``file_conflicts``, hashes) are
        surfaced so a recovery shell can render a useful error message
        without re-deriving the inputs.
        """
        # ------------------------------------------------------------------
        # Step 1: Read the latest Checkpoint. No Checkpoint → cannot
        # resume (SOP §10.1 condition 1 fails).
        # ------------------------------------------------------------------
        checkpoint = session.latest_checkpoint()
        if checkpoint is None:
            return ResumeDecision(
                can_auto_resume=False,
                status="recovery_required",
                reason=(
                    f"no Checkpoint exists for run {session.run_id!r}; "
                    f"cannot resume without a safe step boundary"
                ),
                last_safe_sequence=0,
                next_node_id=None,
                pending_operations=[],
                file_conflicts=[],
                current_registry_hash=self._registry.registry_hash,
                checkpoint_registry_hash=None,
                recommended_action="initiate_recovery",
            )

        # ------------------------------------------------------------------
        # Step 2: Schema version gate. A future v2 schema would require
        # a migration step the coordinator does not yet implement.
        # ------------------------------------------------------------------
        if checkpoint.schema_version not in SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS:
            return ResumeDecision(
                can_auto_resume=False,
                status="recovery_required",
                reason=(
                    f"Checkpoint schema_version="
                    f"{checkpoint.schema_version!r} is not in the "
                    f"supported set "
                    f"{sorted(SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS)!r}; "
                    f"a migration step is required before resume"
                ),
                last_safe_sequence=checkpoint.last_committed_sequence,
                next_node_id=checkpoint.next_node_id,
                pending_operations=[],
                file_conflicts=[],
                current_registry_hash=self._registry.registry_hash,
                checkpoint_registry_hash=checkpoint.checkpoint_registry_hash,
                recommended_action="initiate_recovery",
            )

        # ------------------------------------------------------------------
        # Step 3: Reconstruct pending operations from the event log
        # (when the caller did not provide them).
        # ------------------------------------------------------------------
        if pending_operations is None:
            events_after = session.list_events(
                since_sequence=checkpoint.last_committed_sequence
            )
            pending_operations = build_pending_operations(events_after)

        # ------------------------------------------------------------------
        # Step 4: Detect active MultiAgent Workers (SOP §10.2: "Worker
        # 在崩溃时仍标记 active"). v0.04 only DETECTS; it does not
        # attempt recovery (SOP §10.3 explicit non-goal).
        # ------------------------------------------------------------------
        active_workers = self._detect_active_workers(session)
        if active_workers:
            return ResumeDecision(
                can_auto_resume=False,
                status="recovery_required",
                reason=(
                    f"{len(active_workers)} task(s) are still marked "
                    f"active/running in TaskState: "
                    f"{[t['task_id'] for t in active_workers]!r}; "
                    f"SOP §10.2 forbids auto-resume while Workers may "
                    f"still be in flight (SOP §10.3 defers recovery)"
                ),
                last_safe_sequence=checkpoint.last_committed_sequence,
                next_node_id=checkpoint.next_node_id,
                pending_operations=pending_operations,
                file_conflicts=[],
                current_registry_hash=self._registry.registry_hash,
                checkpoint_registry_hash=checkpoint.checkpoint_registry_hash,
                recommended_action="initiate_recovery",
            )

        # ------------------------------------------------------------------
        # Step 5: Delegate to evaluate_resume_safety (P0-C) for the
        # core decision: registry membership + hash + pending ops +
        # file snapshots.
        # ------------------------------------------------------------------
        file_verifier = None
        if self._file_verifier is not None and checkpoint.file_snapshots:
            file_verifier = self._file_verifier.verify

        return evaluate_resume_safety(
            checkpoint=checkpoint,
            current_registry=self._registry,
            pending_operations=pending_operations,
            file_snapshot_verifier=file_verifier,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _detect_active_workers(
        self, session: "SessionService"
    ) -> list[dict[str, Any]]:
        """Return TaskState rows that mark a Worker as still in-flight.

        SOP §10.2: "MultiAgent Worker 在崩溃时仍标记 active" → must stop.
        v0.04 detects the condition; recovery is explicitly deferred
        (SOP §10.3). The returned list carries ``task_id`` and ``status``
        so a recovery shell can surface them in an error message.

        The statuses considered "active" are deliberately conservative:
        ``active``, ``running``, ``started``. ``completed`` and
        ``failed`` are NOT active. ``unknown`` (if a future version
        emits it) is treated as NOT active — the operator must
        explicitly mark it active before this check will block.
        """
        try:
            states = session.list_task_states()
        except Exception:
            # Defensive: if TaskState reads fail (corrupt row, schema
            # mismatch), do NOT silently allow resume. Return a sentinel
            # entry so the caller sees "TaskState unreadable" in the
            # reason rather than a silent ok.
            return [{"task_id": "<unknown>", "status": "<unreadable>"}]

        active = []
        for state in states:
            status = state.get("status")
            if status in ACTIVE_TASK_STATUSES:
                active.append(state)
        return active
