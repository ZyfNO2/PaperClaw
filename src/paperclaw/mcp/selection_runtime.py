"""Runtime wiring for MCP capability selection without Prompt construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from paperclaw.context.source_registry import (
    ContextSourceDescriptor,
    ContextSourceRegistry,
)
from paperclaw.mcp.runtime import MCPRuntimeConnection, MCPRuntimeTool
from paperclaw.mcp.selection import (
    MCPCapabilityContextSource,
    MCPCapabilityIndex,
    MCPCapabilityIndexSnapshot,
    MCPCapabilitySelector,
    MCPSelectionPermissionPolicy,
)
from paperclaw.tools.registry import ToolRegistry


@dataclass(frozen=True)
class MCPSelectionRuntimeBinding:
    """Frozen objects needed by the Context Runtime and offline Eval."""

    index_snapshot: MCPCapabilityIndexSnapshot
    source_descriptor: ContextSourceDescriptor
    source: MCPCapabilityContextSource


def configure_mcp_capability_selection(
    *,
    tool_registry: ToolRegistry,
    context_source_registry: ContextSourceRegistry,
    connections: Iterable[MCPRuntimeConnection],
    permission_policy: MCPSelectionPermissionPolicy,
    top_k: int = 5,
    source_id: str = "mcp.capability_selection",
    source_priority: int = 100,
    scopes_by_tool: Mapping[str, Iterable[str]] | None = None,
    keywords_by_tool: Mapping[str, Iterable[str]] | None = None,
) -> MCPSelectionRuntimeBinding:
    """Create one frozen selection source and register it with v0.08 Context.

    Invocation Permission is deliberately not configured here. The registered
    ``MCPRuntimeTool`` still revalidates its own invocation-time policy.
    """

    index = MCPCapabilityIndex()
    for connection in connections:
        index.add_connection(
            connection,
            scopes_by_tool=scopes_by_tool,
            keywords_by_tool=keywords_by_tool,
        )
    snapshot = index.freeze()
    _isolate_remote_descriptions(tool_registry, snapshot)
    selector = MCPCapabilitySelector(
        snapshot,
        permission_policy=permission_policy,
    )
    source = MCPCapabilityContextSource(selector, top_k=top_k)
    descriptor = context_source_registry.register(
        source_id,
        source,
        kind="tool_selection",
        priority=source_priority,
        scopes=("shared",),
    )
    return MCPSelectionRuntimeBinding(snapshot, descriptor, source)


def _isolate_remote_descriptions(
    registry: ToolRegistry,
    snapshot: MCPCapabilityIndexSnapshot,
) -> None:
    for capability in snapshot.capabilities:
        try:
            tool = registry.get(capability.registry_tool_name)
        except KeyError as exc:
            raise ValueError(
                "capability index references an unregistered MCP Runtime Tool: "
                f"{capability.registry_tool_name}"
            ) from exc
        if not isinstance(tool, MCPRuntimeTool):
            raise ValueError(
                f"registered Tool {capability.registry_tool_name} is not an MCP Runtime Tool"
            )
        if tool.descriptor.qualified_name != capability.qualified_name:
            raise ValueError("MCP Runtime Tool identity does not match capability metadata")
        tool.description = (
            f"Remote MCP tool {capability.registry_tool_name}. "
            "Detailed server metadata is available only when selected through "
            "the untrusted ContextSource boundary. Invocation still requires "
            "schema validation and permission recheck."
        )


__all__ = [
    "MCPSelectionRuntimeBinding",
    "configure_mcp_capability_selection",
]
