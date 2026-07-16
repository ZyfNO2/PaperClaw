"""Model Context Protocol client foundation."""

from paperclaw.mcp.contracts import (
    MCP_PROTOCOL_VERSION,
    MCPCapabilitySnapshot,
    MCPConnectionState,
    MCPError,
    MCPInvocationRequest,
    MCPInvocationResult,
    MCPServerConfig,
    MCPServerIdentity,
    MCPToolDescriptor,
)
from paperclaw.mcp.schema import normalize_json_schema, normalize_tool_descriptor
from paperclaw.mcp.session import MCPClientSession
from paperclaw.mcp.transport import MCPTransport, StdioMCPTransport

__all__ = [
    "MCP_PROTOCOL_VERSION",
    "MCPCapabilitySnapshot",
    "MCPClientSession",
    "MCPConnectionState",
    "MCPError",
    "MCPInvocationRequest",
    "MCPInvocationResult",
    "MCPServerConfig",
    "MCPServerIdentity",
    "MCPToolDescriptor",
    "MCPTransport",
    "StdioMCPTransport",
    "normalize_json_schema",
    "normalize_tool_descriptor",
]
