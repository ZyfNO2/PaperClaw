"""Node-safe MCP Tool registration for the existing PaperClaw runtime."""

from __future__ import annotations

import hashlib
import re
from typing import Callable, Iterable

from paperclaw.mcp.contracts import (
    MCPError,
    MCPServerConfig,
    MCPToolDescriptor,
    bounded_text,
)
from paperclaw.mcp.runtime import (
    DenyAllMCPPermissionPolicy,
    MCPPermissionPolicy,
    MCPRegistrationResult,
    MCPRuntimeConnection as _BaseMCPRuntimeConnection,
)
from paperclaw.mcp.session import MCPClientSession
from paperclaw.tools.registry import ToolRegistry

_NODE_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def mcp_registry_tool_name(descriptor: MCPToolDescriptor) -> str:
    """Return a stable Tool/NodeRegistry-compatible name.

    ``NodeRegistry`` deliberately allows only letters, digits, ``:``, ``_`` and
    ``-``. MCP names may contain dots, so the public Tool name uses bounded
    readable slugs plus a digest over the exact remote identity. The digest
    prevents collisions such as ``a.b`` versus ``a_b``.
    """

    server_slug = _slug(descriptor.server_id, limit=24)
    tool_slug = _slug(descriptor.name, limit=36)
    digest = hashlib.sha256(
        f"{descriptor.server_id}\0{descriptor.name}".encode("utf-8")
    ).hexdigest()[:12]
    return f"mcp_{server_slug}_{tool_slug}_{digest}"


class MCPRuntimeConnection(_BaseMCPRuntimeConnection):
    """Runtime connection whose Tool names satisfy NodeRegistry constraints."""

    def tool_name(self, descriptor: MCPToolDescriptor) -> str:
        return mcp_registry_tool_name(descriptor)


def connect_and_register_mcp_tools(
    registry: ToolRegistry,
    config: MCPServerConfig,
    *,
    permission_policy: MCPPermissionPolicy | None = None,
    tool_prefix: str = "mcp",
    timeout_seconds: float | None = None,
    secret_values: Iterable[str] = (),
    session_factory: Callable[[MCPServerConfig], MCPClientSession] = MCPClientSession,
) -> MCPRegistrationResult:
    """Connect/discover/register atomically without breaking local Tools.

    ``tool_prefix`` is retained for API compatibility with the first internal
    adapter draft. Registry naming is now fixed by ``mcp_registry_tool_name`` so
    callers cannot accidentally introduce NodeRegistry-incompatible names.
    """

    if tool_prefix != "mcp":
        return MCPRegistrationResult(
            server_id=config.server_id,
            registered_tools=(),
            error_code="INVALID_TOOL_PREFIX",
            error_message="custom MCP tool prefixes are not supported",
        )

    session: MCPClientSession | None = None
    try:
        session = session_factory(config)
        session.connect()
        session.initialize()
        descriptors = session.discover()
        connection = MCPRuntimeConnection(
            session,
            descriptors,
            permission_policy=permission_policy or DenyAllMCPPermissionPolicy(),
            tool_prefix=tool_prefix,
            timeout_seconds=timeout_seconds,
            secret_values=(
                *(value for _, value in config.environment),
                *tuple(secret_values),
            ),
        )
        tools = connection.build_tools()
        names = tuple(tool.name for tool in tools)
        existing = set(registry.names)
        collision = next((name for name in names if name in existing), None)
        if collision is not None or len(names) != len(set(names)):
            connection.close()
            return MCPRegistrationResult(
                server_id=config.server_id,
                registered_tools=(),
                error_code="REGISTRY_CONFLICT",
                error_message=(
                    f"MCP ToolRegistry name collision: {collision}"
                    if collision is not None
                    else "MCP discovery produced duplicate ToolRegistry names"
                ),
            )
        for tool in tools:
            registry.register(tool)
        return MCPRegistrationResult(
            server_id=config.server_id,
            registered_tools=names,
            connection=connection,
        )
    except MCPError as exc:
        if session is not None:
            try:
                session.close()
            except MCPError:
                pass
        return MCPRegistrationResult(
            server_id=config.server_id,
            registered_tools=(),
            error_code=exc.code,
            error_message=bounded_text(str(exc), 300),
        )
    except Exception as exc:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        return MCPRegistrationResult(
            server_id=config.server_id,
            registered_tools=(),
            error_code="RUNTIME_INTEGRATION_FAILED",
            error_message=f"MCP runtime integration failed: {type(exc).__name__}",
        )


def _slug(value: str, *, limit: int) -> str:
    slug = _NODE_SAFE.sub("_", value).strip("_-") or "tool"
    return slug[:limit]
