"""InstrumentedFlowRunner: PocketFlow orchestration with event emission.

This module implements Addendum P0-B. The runner WRAPS (not subclasses)
``pocketflow.Flow`` to add:

- Stable node identity resolution (P0-A registry + node_id attribute).
- 7 structured events (flow.started, node.started, node.completed,
  node.failed, transition.selected, checkpoint.committed, flow.stopped).
- Cooperative cancellation between nodes.
- Resume entry-point resolution (full checkpoint reading is P0-C).
- Parity mode: when all services are None, delegates to native
  ``Flow.run`` for byte-for-byte identical business results.

Design decisions (Addendum §4.5 invariants preserved):

1. **Wrap, not subclass.** Subclassing Flow would couple the runner to
   PocketFlow's internal ``_orch`` implementation. Wrapping lets us
   replicate the orchestration loop in our own code while delegating to
   ``Flow.run`` in parity mode. If PocketFlow's ``_orch`` changes, only the
   instrumented loop needs updating; the parity path stays correct.

2. **Parity short-circuit.** When ``event_sink``, ``checkpoint_writer``,
   ``cancellation_token`` are all None AND ``resume_point`` is None, the
   runner calls ``flow.run(shared)`` directly. This guarantees byte-for-byte
   parity with native PocketFlow — no event emission, no shallow-copy
   divergence, no extra attribute reads. This is the v0.04 hard gate
   (``test_instrumented_flow_parity``).

3. **Shallow-copy per iteration.** The instrumented loop replicates
   ``Flow._orch``'s ``copy.copy(curr)`` at the start and after each
   transition. This preserves PocketFlow's per-iteration node isolation
   (PB2 invariant #6): parameter mutations on one iteration do not leak to
   the next.

4. **Phase-split error classification.** For non-Flow nodes, the runner
   calls ``prep`` → ``_exec`` → ``post`` separately so a failure can be
   labeled ``NODE_PREP_FAILED`` / ``NODE_EXEC_FAILED`` / ``NODE_POST_FAILED``.
   ``_exec`` (not ``exec``) is called to preserve Node's retry/fallback
   loop (PB2 invariant #4). For nested Flow nodes, ``_run`` is called
   directly and any error is labeled ``NODE_EXEC_FAILED``.

5. **Exception re-raise.** Per Addendum §4.4, exceptions MUST NOT be
   swallowed. The runner emits ``node.failed`` with the stable error code,
   then re-raises the original exception. ``flow.stopped`` is NOT emitted
   on crash — the exception propagates above the loop and the caller is
   responsible for terminal handling.

6. **Cancellation between nodes.** The token is checked at the TOP of each
   loop iteration (before ``node.started``). Long ``exec`` calls (model
   inference, Bash) may still complete before the token is observed — this
   matches the v0.01–v0.03 cooperative cancellation semantics. The token
   API: ``is_cancelled: bool`` attribute preferred; ``is_set()`` callable
   (threading.Event-style) supported as fallback.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from pocketflow import Flow

from paperclaw.runtime.error_codes import (
    NODE_IDENTITY_MISSING,
    RESUME_REGISTRY_MISMATCH,
    classify_exception,
)
from paperclaw.runtime.flow_contracts import FlowResumePoint, RuntimeServices

#: Event schema version. Bumping this is a replay-compatibility change.
EVENT_SCHEMA_VERSION = 1

#: Maximum characters of the exception message included in ``node.failed``
#: event payloads. Long tracebacks (e.g. from model SDKs) would bloat the
#: event store without aiding diagnosis; the full traceback belongs in logs.
_MAX_ERROR_MESSAGE_LEN = 500


class InstrumentedFlowRunner:
    """Orchestrates a PocketFlow Flow with structured event emission.

    Usage (parity mode — identical to native PocketFlow)::

        runner = InstrumentedFlowRunner()
        runner.run(flow, shared, services=RuntimeServices())

    Usage (instrumented mode — events + cancellation)::

        services = RuntimeServices(
            event_sink=session.sink,
            node_registry=registry,
            cancellation_token=token,
        )
        runner = InstrumentedFlowRunner()
        runner.run(flow, shared, services=services)

    The runner is stateless across ``run`` calls; all per-run state lives in
    local variables. This makes it safe to reuse one runner instance across
    multiple flows or sessions.
    """

    def run(
        self,
        flow: Flow,
        shared: dict[str, Any],
        *,
        services: RuntimeServices,
        resume_point: FlowResumePoint | None = None,
    ) -> Any:
        """Execute ``flow`` over ``shared`` with optional instrumentation.

        Returns the last ``post`` return value (the final action), matching
        ``Flow.run``'s return contract.

        Parity mode (Addendum PB5): when ``services.event_sink`` is None AND
        ``services.checkpoint_writer`` is None AND
        ``services.cancellation_token`` is None AND ``resume_point`` is None,
        delegates to ``flow.run(shared)`` for byte-for-byte identical results.

        Instrumented mode: replicates ``Flow._orch``'s loop with event
        emission, cancellation checks, and phase-split error classification.
        Exceptions from nodes are re-raised after emitting ``node.failed``.

        Args:
            flow: The PocketFlow Flow to execute. Must not be modified by
                the runner; the runner only reads ``flow.start_node``,
                ``flow.params``, and calls ``flow.get_next_node``.
            shared: The authoritative business state dict. Passed by
                reference to each node's prep/exec/post (PB2 invariant #5).
            services: Runtime services bundle. When all optional fields are
                None and ``resume_point`` is None, parity mode activates.
            resume_point: Optional checkpoint resume entry. When provided,
                the runner starts at ``resume_point.next_node_id`` instead
                of ``flow.start_node``. Requires ``services.node_registry``
                to be non-None.

        Returns:
            The last action returned by a node's ``post`` hook, or None if
            the flow ended without executing any node.

        Raises:
            NodeIdentityMissingError: A node has no ``node_id`` and is not
                in the registry.
            ResumeRegistryMismatchError: ``resume_point`` was provided but
                the registry is None or cannot resolve ``next_node_id``.
            Exception: Any exception raised by a node's prep/exec/post is
                re-raised after the ``node.failed`` event is emitted.
        """
        # Parity short-circuit: when no services and no resume, delegate to
        # native Flow.run. This guarantees byte-for-byte parity (PB5 hard
        # gate) because the instrumented loop is never entered.
        if (
            services.event_sink is None
            and services.checkpoint_writer is None
            and services.cancellation_token is None
            and resume_point is None
        ):
            return flow.run(shared)

        run_id = (
            resume_point.run_id
            if resume_point is not None
            else f"run-{uuid.uuid4().hex[:12]}"
        )
        event_sink = services.event_sink
        registry = services.node_registry
        token = services.cancellation_token

        # ------------------------------------------------------------------
        # Resolve the starting node.
        # ------------------------------------------------------------------
        # In resume mode, enter at resume_point.next_node_id (Addendum §5.3:
        # resume object is the NEXT node, never a replay of the completed
        # node). In fresh mode, start at flow.start_node.
        if resume_point is not None:
            if registry is None:
                # Without a registry we cannot resolve next_node_id to a Node.
                # Raise with the stable code so callers can distinguish this
                # from a generic KeyError.
                raise ResumeRegistryMismatchError(
                    f"resume_point references next_node_id="
                    f"{resume_point.next_node_id!r} but services.node_registry "
                    "is None; cannot resolve"
                )
            try:
                start_node = registry.get(resume_point.next_node_id)
            except KeyError as exc:
                raise ResumeRegistryMismatchError(
                    f"next_node_id {resume_point.next_node_id!r} not in registry"
                ) from exc
            start_node_id = resume_point.next_node_id
            resume_from = resume_point.completed_node_id
        else:
            start_node = flow.start_node
            start_node_id = self._resolve_node_id(start_node, registry)
            resume_from = None

        # Emit flow.started (first event of the run).
        _emit_event(event_sink, "flow.started", {
            "run_id": run_id,
            "start_node_id": start_node_id,
            "resume_from": resume_from,
        })

        # ------------------------------------------------------------------
        # Replicate Flow._orch's loop.
        # ------------------------------------------------------------------
        # PocketFlow _orch:
        #   curr, p, last_action = copy.copy(self.start_node), {**self.params}, None
        #   while curr:
        #       curr.set_params(p)
        #       last_action = curr._run(shared)
        #       curr = copy.copy(self.get_next_node(curr, last_action))
        #   return last_action
        #
        # The instrumented loop mirrors this structure exactly, with event
        # emission and cancellation checks added at safe step boundaries.
        params = {**flow.params}
        # Shallow-copy the start node to match _orch's per-iteration
        # isolation (PB2 invariant #6). set_params on the copy does not
        # mutate the original node's params.
        curr = copy.copy(start_node) if start_node is not None else None
        last_action: Any = None
        step_count = 0
        state_revision = 0
        last_node_id: str | None = None
        last_committed_sequence = 0

        while curr is not None:
            # Cooperative cancellation: check BEFORE running the node. Long
            # exec calls may still complete before observation — this matches
            # v0.01–v0.03 semantics. The token is checked here (not inside
            # exec) so a node's internal retry loop is not interrupted.
            if self._is_cancelled(token):
                _emit_event(event_sink, "flow.stopped", {
                    "run_id": run_id,
                    "stop_reason": "cancelled",
                    "last_node_id": last_node_id,
                    "step_count": step_count,
                })
                return last_action

            # set_params on the copy, matching _orch's curr.set_params(p).
            curr.set_params(params)
            node_id = self._resolve_node_id(curr, registry)
            step_count += 1

            # Emit node.started BEFORE prep/exec/post (Addendum §5.2 order:
            # node.started persisted before node executes).
            _emit_event(event_sink, "node.started", {
                "run_id": run_id,
                "node_id": node_id,
                "step_count": step_count,
            })

            # Execute prep → _exec → post with phase-split error
            # classification. For Flow nodes, delegate to _run.
            action, phase_exc = self._run_node_phased(curr, shared)
            if phase_exc is not None:
                phase, exc = phase_exc
                error_code = classify_exception(node_id, phase, exc)
                _emit_event(event_sink, "node.failed", {
                    "run_id": run_id,
                    "node_id": node_id,
                    "step_count": step_count,
                    "error_type": type(exc).__name__,
                    "error_code": error_code,
                    "error_message": str(exc)[:_MAX_ERROR_MESSAGE_LEN],
                })
                # Re-raise the original exception (Addendum §4.4: MUST NOT
                # swallow). flow.stopped is NOT emitted here because the
                # exception propagates above this loop; the caller is
                # responsible for handling the crash.
                raise exc

            last_action = action
            last_node_id = node_id
            state_revision += 1

            # Resolve the successor node. Uses Flow.get_next_node to match
            # PocketFlow's transition semantics (None action → default edge;
            # unknown action → warn and end). PB2 invariants #2, #3.
            next_node = flow.get_next_node(curr, action)
            next_node_id: str | None = None
            if next_node is not None:
                next_node_id = self._resolve_node_id(next_node, registry)

            # Emit node.completed AFTER the node's post returns and state
            # is committed (Addendum §5.2: node business result persisted
            # before transition.selected).
            seq = _emit_event(event_sink, "node.completed", {
                "run_id": run_id,
                "node_id": node_id,
                "action": action,
                "next_node_id": next_node_id,
                "step_count": step_count,
                "state_revision": state_revision,
            })
            if seq > 0:
                last_committed_sequence = seq

            # Emit transition.selected with action + next_node_id (PB4).
            seq = _emit_event(event_sink, "transition.selected", {
                "run_id": run_id,
                "from_node_id": node_id,
                "action": action,
                "to_node_id": next_node_id,
            })
            if seq > 0:
                last_committed_sequence = seq

            # Checkpoint commit (P0-B stub: call writer if non-None, then
            # emit checkpoint.committed). P0-C wires the real writer and
            # defines the error-handling contract. For P0-B, writer failures
            # are swallowed so a checkpoint bug cannot crash the run.
            if services.checkpoint_writer is not None:
                try:
                    services.checkpoint_writer({
                        "run_id": run_id,
                        "completed_node_id": node_id,
                        "last_action": action,
                        "next_node_id": next_node_id,
                        "last_committed_sequence": last_committed_sequence,
                        "state_revision": state_revision,
                    })
                except Exception:
                    # P0-B: checkpoint writer failures are non-fatal.
                    # P0-C will define whether this should raise or
                    # trigger recovery_required.
                    pass
                seq = _emit_event(event_sink, "checkpoint.committed", {
                    "run_id": run_id,
                    "last_node_id": node_id,
                    "next_node_id": next_node_id,
                    "last_committed_sequence": last_committed_sequence,
                    "state_revision": state_revision,
                })
                if seq > 0:
                    last_committed_sequence = seq

            # Advance to the next node. Shallow-copy to match _orch's
            # per-iteration isolation.
            curr = copy.copy(next_node) if next_node is not None else None

        # Flow ended naturally (curr is None). Emit flow.stopped.
        # Use shared["stop_reason"] if a node set one (e.g. CompletedNode
        # sets "done"); fall back to "done" for flows that don't use
        # CompletedNode.
        stop_reason = shared.get("stop_reason") or "done"
        _emit_event(event_sink, "flow.stopped", {
            "run_id": run_id,
            "stop_reason": stop_reason,
            "last_node_id": last_node_id,
            "step_count": step_count,
        })
        return last_action

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_node_id(self, node: Any, registry: Any) -> str:
        """Resolve a stable ``node_id`` for ``node``.

        Order of precedence:

        1. ``node.node_id`` attribute (class or instance) — preferred.
           This is what P0-A assigns to every node in the Agent Flow.
        2. ``registry.get_id(node)`` — for nodes registered without an
           attribute (defensive; P0-A uses attributes).
        3. Raise ``NodeIdentityMissingError`` (stable code
           ``NODE_IDENTITY_MISSING``).

        P0-A should ensure every node has a ``node_id``, but the runner
        checks defensively so an anonymous ``Node()`` cannot silently
        produce an untraceable event.
        """
        nid = getattr(node, "node_id", None)
        if isinstance(nid, str) and nid:
            return nid
        if registry is not None:
            try:
                return registry.get_id(node)
            except KeyError:
                pass
        raise NodeIdentityMissingError(
            f"node {node!r} has no node_id attribute and is not in the registry"
        )

    def _run_node_phased(
        self,
        curr: Any,
        shared: dict[str, Any],
    ) -> tuple[Any, tuple[str, BaseException] | None]:
        """Run ``prep → _exec → post`` with phase-split error classification.

        Returns ``(action, None)`` on success or ``(None, (phase, exc))`` on
        failure. For Flow nodes, delegates to ``_run`` and labels any error
        as ``"exec"`` phase (Flow's internal _orch is opaque to the runner).

        PB2 invariants preserved:

        - #1: prep → exec → post order.
        - #4: ``_exec`` (not ``exec``) is called to preserve retry/fallback.
          ``Node._exec`` contains the retry loop and ``exec_fallback`` call;
          bypassing it would break retry semantics.
        - #5: shared is the authoritative state; no copy is made. The same
          dict reference is passed to prep, _exec, and post so mutations
          are visible to subsequent phases and nodes.

        Why split phases instead of calling ``_run`` directly? Because
        ``_run`` is a single try/except boundary — we cannot tell whether
        ``prep``, ``exec``, or ``post`` raised. Phase-splitting lets the
        runner emit ``NODE_PREP_FAILED`` vs ``NODE_EXEC_FAILED`` vs
        ``NODE_POST_FAILED`` (PB6), which a resume or replay needs to decide
        whether the node's side effects are safe to skip.

        For nested Flow nodes (``isinstance(curr, Flow)``), we do NOT split
        phases because ``Flow._run`` calls ``_orch`` internally and the
        phase boundary is opaque. Any error is labeled ``"exec"``.
        """
        if isinstance(curr, Flow):
            # Nested Flow: _run calls _orch internally. We don't split
            # phases for nested flows because Flow._run is a single unit
            # and its internal _orch has its own retry/transition logic.
            try:
                return curr._run(shared), None
            except Exception as exc:
                return None, ("exec", exc)

        # Non-Flow node: split phases for fine-grained error classification.
        # This is semantically identical to BaseNode._run:
        #   p = self.prep(shared); e = self._exec(p); return self.post(shared, p, e)
        # The only difference is we wrap each phase in its own try/except.
        try:
            prep_res = curr.prep(shared)
        except Exception as exc:
            return None, ("prep", exc)
        try:
            exec_res = curr._exec(prep_res)
        except Exception as exc:
            return None, ("exec", exc)
        try:
            action = curr.post(shared, prep_res, exec_res)
        except Exception as exc:
            return None, ("post", exc)
        return action, None

    def _is_cancelled(self, token: Any) -> bool:
        """Check the cooperative cancellation token.

        API (pick one):

        - ``is_cancelled: bool`` attribute — preferred. Simple boolean flag
          that the caller sets to True to request cancellation.
        - ``is_set()`` callable — fallback for ``threading.Event``-style
          tokens, which v0.01–v0.03 used as ``cancel_event``.

        Returns ``False`` when ``token is None`` (no cancellation requested).
        The token is checked between nodes, not inside ``exec``, so a
        long-running tool call may still complete before the token is
        observed. This matches the cooperative cancellation semantics of
        v0.01–v0.03.
        """
        if token is None:
            return False
        # Prefer the is_cancelled bool attribute (explicit, no callable
        # overhead, clear intent).
        ic = getattr(token, "is_cancelled", None)
        if isinstance(ic, bool):
            return ic
        # Fall back to is_set() for threading.Event compatibility.
        is_set = getattr(token, "is_set", None)
        if callable(is_set):
            return bool(is_set())
        return False


# ---------------------------------------------------------------------------
# Exception types for stable error codes
# ---------------------------------------------------------------------------


class NodeIdentityMissingError(Exception):
    """Raised when a node has no ``node_id`` and is not in the registry.

    Stable error code: ``NODE_IDENTITY_MISSING``. P0-A should prevent this,
    but the runner checks defensively (Addendum §4.2 responsibility #2).

    The ``error_code`` class attribute lets tests and callers verify the
    stable code without parsing the exception message.
    """

    error_code = NODE_IDENTITY_MISSING


class ResumeRegistryMismatchError(Exception):
    """Raised when ``resume_point`` is given but the registry cannot resolve
    ``next_node_id``.

    Stable error code: ``RESUME_REGISTRY_MISMATCH``. Full cross-version
    registry-hash checking is P0-C; P0-B only checks existence (registry is
    None or ``next_node_id`` not in registry).

    The ``error_code`` class attribute lets tests and callers verify the
    stable code without parsing the exception message.
    """

    error_code = RESUME_REGISTRY_MISMATCH


# ---------------------------------------------------------------------------
# Event emission helper (module-level)
# ---------------------------------------------------------------------------


def _emit_event(sink: Any, event_type: str, payload: dict[str, Any]) -> int:
    """Emit one event to the sink. No-op (returns 0) when sink is None.

    Returns the assigned sequence number from the sink. The caller uses
    non-zero sequences to track ``last_committed_sequence`` for checkpoint
    payloads. A return of 0 means "sink does not allocate sequences"
    (NullEventSink or None sink) — callers MUST NOT treat 0 as an error.

    Per Addendum §4.4: event ordering MUST NOT rely on timestamp alone.
    The sequence returned by the sink is the authoritative ordering key.

    The payload is augmented with ``schema_version`` and ``event_type``
    before emission so every persisted event is self-describing. The
    caller's payload dict is NOT mutated — a shallow copy is made.
    """
    if sink is None:
        return 0
    # Build the persisted payload without mutating the caller's dict.
    # schema_version is set per Addendum §4.4 common schema.
    persisted = dict(payload)
    persisted.setdefault("schema_version", EVENT_SCHEMA_VERSION)
    persisted["event_type"] = event_type
    return sink.emit(event_type, persisted)
