from __future__ import annotations

from pathlib import Path

from pocketflow import Flow, Node

from paperclaw.models.base import ChatModel
from paperclaw.tools import BashTool, FileEditTool, FileReadTool, FileWriteTool, GrepTool, ToolRegistry

from .nodes import DecideActionNode, ExecuteToolNode
from .state import initial_state


def default_registry() -> ToolRegistry:
    return ToolRegistry([FileReadTool(), FileWriteTool(), FileEditTool(), GrepTool(), BashTool()])


def build_react_flow(model: ChatModel, registry: ToolRegistry | None = None) -> Flow:
    registry = registry or default_registry()
    decide = DecideActionNode(model, registry)
    execute_nodes = {name: ExecuteToolNode(registry) for name in registry.names}
    for name, node in execute_nodes.items():
        decide - name >> node
        node >> decide
    decide - "retry" >> decide
    decide - "done" >> Node()
    return Flow(start=decide)


class AgentRuntime:
    def __init__(self, model: ChatModel, registry: ToolRegistry | None = None) -> None:
        self.flow = build_react_flow(model, registry)

    def run(self, task: str, workspace: Path | str, max_steps: int = 12, event_handler=None) -> dict:
        if not task.strip():
            raise ValueError("task must not be empty")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        shared = initial_state(task, Path(workspace), max_steps)
        shared["event_handler"] = event_handler
        self.flow.run(shared)
        return shared
