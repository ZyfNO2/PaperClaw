"""Runtime dataclasses shared by InstrumentedFlowRunner (P0-B) and
Checkpoint wiring (P0-C).

P0-A only ships the dataclasses; the runner that consumes them is
Addendum P0-B. Defining the contracts first keeps the node-identity work
in P0-A honest: ``FlowResumePoint`` references ``next_node_id`` and
``completed_node_id`` as strings, which forces P0-A to provide stable IDs
before P0-B can wire resume.

Per Addendum §4.3 the goal is to replace ad-hoc ``Flow.params`` stuffing
with a single ``RuntimeServices`` dataclass. ``params`` remains the
PocketFlow-compatible entry point for callers that do not opt in to the
Runtime yet (parity mode).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from paperclaw.context.session import EventSink
    from paperclaw.runtime.node_registry import NodeRegistry


@dataclass(frozen=True)
class FlowResumePoint:
    """Where to resume a Flow after a checkpointed step boundary.

    Per Addendum §5.3 the resume object is the NEXT node, never a replay of
    the completed node. ``completed_node_id`` is recorded for traceability
    and audit only; the runner MUST enter at ``next_node_id``.

    Fields mirror what a Checkpoint stores (Addendum §5.1):

    - ``run_id``: the SessionService run this resume belongs to.
    - ``completed_node_id``: the last node that successfully committed a
      Checkpoint. ``None`` means "fresh start, no node has run yet".
    - ``last_action``: the action (transition label) that selected
      ``next_node_id`` from ``completed_node_id``. ``None`` for the first node.
    - ``next_node_id``: the node the runner will execute on resume.
    - ``last_committed_sequence``: the SessionEvent sequence at the last
      safe boundary. Resume MUST NOT emit events with lower sequences.
    - ``state_revision``: the TaskState revision at the checkpoint. Used to
      detect that the runtime's in-memory state is in sync with the
      persisted state before resuming.
    """

    run_id: str
    completed_node_id: str | None
    last_action: str | None
    next_node_id: str
    last_committed_sequence: int
    state_revision: int


@dataclass
class RuntimeServices:
    """Bundle of runtime services passed to ``InstrumentedFlowRunner.run``.

    Replaces the v0.01–v0.03 pattern of stuffing ``event_handler``,
    ``cancel_event``, etc. into ``shared``. Each field is optional so a
    parity-mode runner (no persistence, no cancellation) can construct an
    empty ``RuntimeServices()`` and behave like the original PocketFlow
    ``Flow.run``.

    Per Addendum §4.3 and §8:

    - ``event_sink``: where ``flow.started`` / ``node.started`` /
      ``node.completed`` / ``transition.selected`` / ``checkpoint.committed``
      / ``flow.stopped`` events go. ``None`` disables persistence
      (parity mode).
    - ``checkpoint_writer``: object responsible for committing Checkpoints
      at safe step boundaries. P0-A declares the field to match §4.3; P0-C
      wires it. Typed as ``Any`` for now because the concrete
      ``CheckpointWriter`` Protocol lands in P0-C — using ``Any`` avoids
      importing a not-yet-existing type.
    - ``node_registry``: the stable identity registry for this Flow. The
      runner uses it to resolve ``next_node_id`` from a resume point.
    - ``cancellation_token``: cooperative cancellation. ``None`` = no
      cancellation. The runner checks the token between nodes, not inside
      node ``exec`` (long tool calls may still complete before exit).
    - ``extra``: escape hatch for future services (Permission Engine,
      Trace collector, Budget). P0-A/B/C do not read this field; it exists
      so v0.05+ can extend without breaking the dataclass.
    """

    event_sink: "EventSink | None" = None
    checkpoint_writer: Any = None
    node_registry: "NodeRegistry | None" = None
    cancellation_token: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
