"""Model Context Protocol client foundation and runtime integration."""

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
from paperclaw.mcp.registration import (
    MCPRuntimeConnection,
    connect_and_register_mcp_tools,
    mcp_registry_tool_name,
)
from paperclaw.mcp.runtime import (
    AllowListMCPPermissionPolicy,
    DenyAllMCPPermissionPolicy,
    MCPPermissionDecision,
    MCPPermissionPolicy,
    MCPRegistrationResult,
    MCPRuntimeTool,
)
from paperclaw.mcp.schema import normalize_json_schema, normalize_tool_descriptor
from paperclaw.mcp.session import MCPClientSession
from paperclaw.mcp.transport import MCPTransport, StdioMCPTransport
from paperclaw.mcp.validation import validate_tool_arguments

__all__ = [
    "MCP_PROTOCOL_VERSION",
    "AllowListMCPPermissionPolicy",
    "DenyAllMCPPermissionPolicy",
    "MCPCapabilitySnapshot",
    "MCPClientSession",
    "MCPConnectionState",
    "MCPError",
    "MCPInvocationRequest",
    "MCPInvocationResult",
    "MCPPermissionDecision",
    "MCPPermissionPolicy",
    "MCPRegistrationResult",
    "MCPRuntimeConnection",
    "MCPRuntimeTool",
    "MCPServerConfig",
    "MCPServerIdentity",
    "MCPToolDescriptor",
    "MCPTransport",
    "StdioMCPTransport",
    "connect_and_register_mcp_tools",
    "mcp_registry_tool_name",
    "normalize_json_schema",
    "normalize_tool_descriptor",
    "validate_tool_arguments",
]
