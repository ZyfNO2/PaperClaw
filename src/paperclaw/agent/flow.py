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
    """Assemble the runtime graph and its stable NodeRegistry."""
    registry = registry or default_registry()
    node_registry = node_registry or NodeRegistry()

    decide = DecideActionNode(model, registry)
    execute_nodes = {name: ExecuteToolNode(registry, tool_name=name) for name in registry.names}

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
        completed = CompletedNode()
        reflect - "done" >> completed
        node_registry.add(verify)
        node_registry.add(reflect)
        node_registry.add(completed)
    else:
        completed = CompletedNode()
        decide - "done" >> completed
        node_registry.add(completed)

    return Flow(start=decide), node_registry


class AgentRuntime:
    """Thin runtime wrapper around the existing PocketFlow graph."""

    def __init__(
        self,
        model: ChatModel,
        registry: ToolRegistry | None = None,
        *,
        enable_verification_gate: bool = False,
    ) -> None:
        self.enable_verification_gate = enable_verification_gate
        self.flow, self.node_registry = build_react_flow(
            model,
            registry,
            enable_verification_gate=enable_verification_gate,
        )
        self.last_state: dict | None = None

    def run(
        self,
        task: str,
        workspace: Path | str,
        max_steps: int = 12,
        event_handler=None,
        cancel_event=None,
        timeout_seconds: int = 0,
        run_id: str | None = None,
    ) -> dict:
        if not task.strip():
            raise ValueError("task must not be empty")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        shared = initial_state(
            task,
            Path(workspace),
            max_steps,
            timeout_seconds=timeout_seconds,
            run_id=run_id,
        )
        self.last_state = shared
        shared["verification_gate_enabled"] = self.enable_verification_gate
        shared["event_handler"] = event_handler
        shared["cancel_event"] = cancel_event
        self.flow.run(shared)
        return shared
