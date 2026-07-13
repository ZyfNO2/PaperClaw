from __future__ import annotations

from pathlib import Path

from pocketflow import Flow, Node

from paperclaw.models.base import ChatModel
from paperclaw.runtime import CompletedNode, NodeRegistry
from paperclaw.tools import BashTool, FileEditTool, FileReadTool, FileWriteTool, GrepTool, ToolRegistry

from .nodes import DecideActionNode, ExecuteToolNode, ReflectNode, VerifyDoneProposalNode
from .state import initial_state


def default_registry() -> ToolRegistry:
    """Build the v0.01 tool surface in one place so later versions can swap registries without changing nodes."""

    return ToolRegistry([FileReadTool(), FileWriteTool(), FileEditTool(), GrepTool(), BashTool()])


def build_react_flow(
    model: ChatModel,
    registry: ToolRegistry | None = None,
    *,
    enable_verification_gate: bool = False,
    node_registry: NodeRegistry | None = None,
) -> tuple[Flow, NodeRegistry]:
    """Assemble the runtime graph and its stable NodeRegistry.

    Returns ``(flow, node_registry)``. The Flow is the PocketFlow graph used
    by the existing AgentRuntime; the NodeRegistry is the PaperClaw-side
    identity map (Addendum §3) used by the InstrumentedFlowRunner (P0-B) to
    resolve ``next_node_id`` from a Checkpoint.

    The verification gate is feature-flagged so v0.02 can grow behind a
    compatibility switch while v0.01 behavior remains reproducible and
    testable.

    Anonymous ``Node()`` terminals are replaced by PaperClaw's
    ``CompletedNode`` (Addendum §3.4) so every reachable state has a stable
    ``node_id`` for Checkpoint and trace.
    """
    registry = registry or default_registry()
    # PaperClaw-side identity map. Defaults to a fresh registry when the
    # caller did not pass one; the InstrumentedFlowRunner (P0-B) will use
    # this to resolve node_id <-> Node at resume time.
    node_registry = node_registry or NodeRegistry()

    decide = DecideActionNode(model, registry)
    execute_nodes = {name: ExecuteToolNode(registry, tool_name=name) for name in registry.names}

    # Register every node that participates in transitions so the registry
    # matches the Flow graph 1:1. The decide node and all execute nodes are
    # always present; verify/reflect/completed depend on the gate flag.
    node_registry.add(decide)
    for node in execute_nodes.values():
        node_registry.add(node)

    for name, node in execute_nodes.items():
        decide - name >> node
        node >> decide
    decide - "retry" >> decide
    if enable_verification_gate:
        verify = VerifyDoneProposalNode()
        reflect = ReflectNode(model)
        decide - "done" >> verify
        verify >> reflect
        reflect - "default" >> decide
        reflect - "reverify" >> verify
        # Replace anonymous `Node()` terminal with explicit CompletedNode.
        completed = CompletedNode()
        reflect - "done" >> completed
        node_registry.add(verify)
        node_registry.add(reflect)
        node_registry.add(completed)
    else:
        # Replace anonymous `Node()` terminal with explicit CompletedNode.
        completed = CompletedNode()
        decide - "done" >> completed
        node_registry.add(completed)

    return Flow(start=decide), node_registry


class AgentRuntime:
    """Thin runtime wrapper around the PocketFlow graph.

    Keeping orchestration here lets the CLI, tests, and future adapters share the same loop without
    reimplementing state bootstrapping or event wiring.
    """

    def __init__(self, model: ChatModel, registry: ToolRegistry | None = None, *, enable_verification_gate: bool = False) -> None:
        self.enable_verification_gate = enable_verification_gate
        # build_react_flow now returns (flow, node_registry) so the runtime
        # carries stable node identity for future InstrumentedFlowRunner (P0-B)
        # and Checkpoint wiring (P0-C). The AgentRuntime itself does not yet
        # consume the registry; it stashes it for the runner that will.
        self.flow, self.node_registry = build_react_flow(
            model, registry, enable_verification_gate=enable_verification_gate
        )

    def run(
        self,
        task: str,
        workspace: Path | str,
        max_steps: int = 12,
        event_handler=None,
        cancel_event=None,
        timeout_seconds: int = 0,
    ) -> dict:
        if not task.strip():
            raise ValueError("task must not be empty")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        shared = initial_state(task, Path(workspace), max_steps, timeout_seconds=timeout_seconds)
        shared["verification_gate_enabled"] = self.enable_verification_gate
        # Event handlers are observational only; runtime state remains authoritative even if no observer is attached.
        shared["event_handler"] = event_handler
        # Cancellation is cooperative: the runtime checks the event between steps
        # so a long-running tool call may still complete before the loop exits.
        shared["cancel_event"] = cancel_event
        self.flow.run(shared)
        return shared
