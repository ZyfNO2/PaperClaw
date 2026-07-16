"""Model Context Protocol client, runtime and capability selection."""

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
from paperclaw.mcp.selection import (
    AllowListMCPSelectionPolicy,
    DenyAllMCPSelectionPolicy,
    MCPCapabilityContextSource,
    MCPCapabilityIndex,
    MCPCapabilityIndexFrozen,
    MCPCapabilityIndexSnapshot,
    MCPCapabilityMetadata,
    MCPCapabilitySelection,
    MCPCapabilitySelectionRequest,
    MCPCapabilitySelector,
    MCPSelectionPermissionDecision,
    MCPSelectionPermissionPolicy,
)
from paperclaw.mcp.selection_evaluation import (
    MCPToolSelectionJudgment,
    MCPToolSelectionMetrics,
    evaluate_tool_selection,
)
from paperclaw.mcp.selection_runtime import (
    MCPSelectionRuntimeBinding,
    configure_mcp_capability_selection,
)
from paperclaw.mcp.session import MCPClientSession
from paperclaw.mcp.transport import MCPTransport, StdioMCPTransport
from paperclaw.mcp.validation import validate_tool_arguments

__all__ = [
    "MCP_PROTOCOL_VERSION",
    "AllowListMCPPermissionPolicy",
    "AllowListMCPSelectionPolicy",
    "DenyAllMCPPermissionPolicy",
    "DenyAllMCPSelectionPolicy",
    "MCPCapabilityContextSource",
    "MCPCapabilityIndex",
    "MCPCapabilityIndexFrozen",
    "MCPCapabilityIndexSnapshot",
    "MCPCapabilityMetadata",
    "MCPCapabilitySelection",
    "MCPCapabilitySelectionRequest",
    "MCPCapabilitySelector",
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
    "MCPSelectionPermissionDecision",
    "MCPSelectionPermissionPolicy",
    "MCPSelectionRuntimeBinding",
    "MCPServerConfig",
    "MCPServerIdentity",
    "MCPToolDescriptor",
    "MCPToolSelectionJudgment",
    "MCPToolSelectionMetrics",
    "MCPTransport",
    "StdioMCPTransport",
    "configure_mcp_capability_selection",
    "connect_and_register_mcp_tools",
    "evaluate_tool_selection",
    "mcp_registry_tool_name",
    "normalize_json_schema",
    "normalize_tool_descriptor",
    "validate_tool_arguments",
]
