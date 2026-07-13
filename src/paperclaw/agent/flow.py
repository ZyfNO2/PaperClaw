from __future__ import annotations

from pathlib import Path

from pocketflow import Flow, Node

from paperclaw.models.base import ChatModel
from paperclaw.tools import BashTool, FileEditTool, FileReadTool, FileWriteTool, GrepTool, ToolRegistry

from .nodes import DecideActionNode, ExecuteToolNode, ReflectNode, VerifyDoneProposalNode
from .state import initial_state


def default_registry() -> ToolRegistry:
    """Build the v0.01 tool surface in one place so later versions can swap registries without changing nodes."""

    return ToolRegistry([FileReadTool(), FileWriteTool(), FileEditTool(), GrepTool(), BashTool()])


def build_react_flow(model: ChatModel, registry: ToolRegistry | None = None, *, enable_verification_gate: bool = False) -> Flow:
    """Assemble the runtime graph.

    The verification gate is feature-flagged so v0.02 can grow behind a compatibility switch while v0.01 behavior
    remains reproducible and testable.
    """

    registry = registry or default_registry()
    decide = DecideActionNode(model, registry)
    execute_nodes = {name: ExecuteToolNode(registry) for name in registry.names}
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
        reflect - "done" >> Node()
    else:
        decide - "done" >> Node()
    return Flow(start=decide)


class AgentRuntime:
    """Thin runtime wrapper around the PocketFlow graph.

    Keeping orchestration here lets the CLI, tests, and future adapters share the same loop without
    reimplementing state bootstrapping or event wiring.
    """

    def __init__(self, model: ChatModel, registry: ToolRegistry | None = None, *, enable_verification_gate: bool = False) -> None:
        self.enable_verification_gate = enable_verification_gate
        self.flow = build_react_flow(model, registry, enable_verification_gate=enable_verification_gate)

    def run(
        self,
        task: str,
        workspace: Path | str,
        max_steps: int = 12,
        event_handler=None,
        cancel_event=None,
    ) -> dict:
        if not task.strip():
            raise ValueError("task must not be empty")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        shared = initial_state(task, Path(workspace), max_steps)
        shared["verification_gate_enabled"] = self.enable_verification_gate
        # Event handlers are observational only; runtime state remains authoritative even if no observer is attached.
        shared["event_handler"] = event_handler
        # Cancellation is cooperative: the runtime checks the event between steps
        # so a long-running tool call may still complete before the loop exits.
        shared["cancel_event"] = cancel_event
        self.flow.run(shared)
        return shared
