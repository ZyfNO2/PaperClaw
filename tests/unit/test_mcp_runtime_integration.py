"""Unit coverage for MCP ToolRegistry and invocation runtime integration."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from paperclaw.mcp import (
    AllowListMCPPermissionPolicy,
    MCPError,
    MCPInvocationResult,
    MCPPermissionDecision,
    MCPServerConfig,
    connect_and_register_mcp_tools,
    normalize_tool_descriptor,
)
from paperclaw.tools.base import (
    ToolContext,
    ToolControlFlow,
    ToolResult,
    safe_execute,
)
from paperclaw.tools.registry import ToolRegistry


class LocalTool:
    name = "local"
    description = "Local regression tool"

    def validate(self, arguments: dict[str, Any]) -> None:
        return None

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(True, "local-ok")


def _descriptor(server_id: str = "fake"):
    return normalize_tool_descriptor(
        {
            "name": "echo",
            "description": "Echo one value",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "count": {"type": "integer", "minimum": 1},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        server_id=server_id,
    )


def _config(*, timeout: float = 0.2, secret: str | None = None) -> MCPServerConfig:
    environment = () if secret is None else (("TEST_SECRET", secret),)
    return MCPServerConfig(
        server_id="fake",
        command=("fake-server",),
        environment=environment,
        request_timeout_seconds=timeout,
    )


class FakeSession:
    def __init__(
        self,
        config: MCPServerConfig,
        *,
        result_text: str = "ok",
        delay: float = 0.0,
        discover_error: MCPError | None = None,
    ) -> None:
        self.config = config
        self.result_text = result_text
        self.delay = delay
        self.discover_error = discover_error
        self.calls = 0
        self.closed = False
        self.call_started = threading.Event()

    def connect(self) -> None:
        return None

    def initialize(self) -> object:
        return object()

    def discover(self):
        if self.discover_error is not None:
            raise self.discover_error
        return (_descriptor(self.config.server_id),)

    def call(self, request):
        self.calls += 1
        self.call_started.set()
        if self.delay:
            time.sleep(self.delay)
        return MCPInvocationResult(
            server_id=self.config.server_id,
            tool_name=request.tool_name,
            request_id=self.calls,
            text_content=(self.result_text,),
            structured_content={"echoed": self.result_text},
            is_error=False,
        )

    def close(self) -> None:
        self.closed = True


class MutablePolicy:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.checks = 0

    def authorize(self, *, descriptor, arguments, context) -> MCPPermissionDecision:
        del descriptor, arguments, context
        self.checks += 1
        return MCPPermissionDecision(self.allowed, "mutable test policy")


class CancelToken:
    def __init__(self) -> None:
        self._cancelled = False
        self._reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str | None:
        return self._reason

    def cancel(self, reason: str) -> None:
        self._cancelled = True
        self._reason = reason


def test_registers_mcp_tools_without_replacing_local_tools(tmp_path: Path) -> None:
    local = LocalTool()
    registry = ToolRegistry([local])
    session = FakeSession(_config())

    registration = connect_and_register_mcp_tools(
        registry,
        session.config,
        permission_policy=AllowListMCPPermissionPolicy(frozenset({"fake.echo"})),
        session_factory=lambda config: session,
    )

    assert registration.ok
    assert registration.registered_tools == ("mcp.fake.echo",)
    assert registry.names == ("local", "mcp.fake.echo")
    assert safe_execute(local, {}, ToolContext(tmp_path)).output == "local-ok"
    assert registration.connection is not None
    registration.connection.close()


def test_schema_validation_blocks_remote_call(tmp_path: Path) -> None:
    registry = ToolRegistry()
    session = FakeSession(_config())
    registration = connect_and_register_mcp_tools(
        registry,
        session.config,
        permission_policy=AllowListMCPPermissionPolicy(frozenset({"fake.echo"})),
        session_factory=lambda config: session,
    )

    result = safe_execute(
        registry.get("mcp.fake.echo"),
        {"text": "", "extra": True},
        ToolContext(tmp_path),
    )

    assert not result.ok
    assert result.error_code == "validation_error"
    assert session.calls == 0
    assert registration.connection is not None
    registration.connection.close()


def test_permission_is_rechecked_for_every_invocation(tmp_path: Path) -> None:
    policy = MutablePolicy(True)
    registry = ToolRegistry()
    session = FakeSession(_config())
    registration = connect_and_register_mcp_tools(
        registry,
        session.config,
        permission_policy=policy,
        session_factory=lambda config: session,
    )
    tool = registry.get("mcp.fake.echo")

    first = safe_execute(tool, {"text": "first"}, ToolContext(tmp_path))
    policy.allowed = False
    second = safe_execute(tool, {"text": "second"}, ToolContext(tmp_path))

    assert first.ok
    assert not second.ok
    assert second.error_code == "validation_error"
    assert "permission denied" in second.output
    assert policy.checks == 2
    assert session.calls == 1
    assert registration.connection is not None
    registration.connection.close()


def test_default_permission_policy_is_fail_closed(tmp_path: Path) -> None:
    registry = ToolRegistry()
    session = FakeSession(_config())
    registration = connect_and_register_mcp_tools(
        registry,
        session.config,
        session_factory=lambda config: session,
    )

    result = safe_execute(
        registry.get("mcp.fake.echo"),
        {"text": "blocked"},
        ToolContext(tmp_path),
    )

    assert not result.ok
    assert "permission denied" in result.output
    assert session.calls == 0
    assert registration.connection is not None
    registration.connection.close()


def test_timeout_closes_remote_connection_but_local_tool_still_works(
    tmp_path: Path,
) -> None:
    local = LocalTool()
    registry = ToolRegistry([local])
    session = FakeSession(_config(timeout=0.05), delay=0.2)
    registration = connect_and_register_mcp_tools(
        registry,
        session.config,
        permission_policy=AllowListMCPPermissionPolicy(frozenset({"fake.echo"})),
        timeout_seconds=0.05,
        session_factory=lambda config: session,
    )

    remote = safe_execute(
        registry.get("mcp.fake.echo"),
        {"text": "slow"},
        ToolContext(tmp_path),
    )
    local_result = safe_execute(local, {}, ToolContext(tmp_path))

    assert not remote.ok
    assert remote.error_code == "mcp_timeout"
    assert session.closed
    assert local_result.ok
    assert local_result.output == "local-ok"


def test_cancellation_terminates_remote_connection(tmp_path: Path) -> None:
    registry = ToolRegistry()
    session = FakeSession(_config(timeout=1.0), delay=0.5)
    registration = connect_and_register_mcp_tools(
        registry,
        session.config,
        permission_policy=AllowListMCPPermissionPolicy(frozenset({"fake.echo"})),
        timeout_seconds=1.0,
        session_factory=lambda config: session,
    )
    token = CancelToken()

    def cancel_after_start() -> None:
        assert session.call_started.wait(timeout=1)
        token.cancel("user_requested")

    threading.Thread(target=cancel_after_start, daemon=True).start()
    with pytest.raises(ToolControlFlow, match="user_requested"):
        safe_execute(
            registry.get("mcp.fake.echo"),
            {"text": "cancel"},
            ToolContext(tmp_path, stop_token=token),
        )

    assert session.closed


def test_output_is_redacted_before_tool_truncation(tmp_path: Path) -> None:
    secret = "supersecret-value"
    registry = ToolRegistry()
    session = FakeSession(
        _config(secret=secret),
        result_text=f"{secret}-suffix-that-is-long",
    )
    registration = connect_and_register_mcp_tools(
        registry,
        session.config,
        permission_policy=AllowListMCPPermissionPolicy(frozenset({"fake.echo"})),
        session_factory=lambda config: session,
    )

    result = safe_execute(
        registry.get("mcp.fake.echo"),
        {"text": "safe"},
        ToolContext(tmp_path, output_limit=14),
    )

    assert result.ok
    assert secret not in result.output
    assert not result.output.startswith(secret[:14])
    assert result.metadata["truncated"] is True
    assert registration.connection is not None
    registration.connection.close()


def test_server_discovery_failure_leaves_local_registry_usable(tmp_path: Path) -> None:
    local = LocalTool()
    registry = ToolRegistry([local])
    error = MCPError(
        "server disconnected",
        code="TRANSPORT_DISCONNECTED",
        retriable=True,
        server_id="fake",
        phase="tools/list",
    )
    session = FakeSession(_config(), discover_error=error)

    registration = connect_and_register_mcp_tools(
        registry,
        session.config,
        permission_policy=AllowListMCPPermissionPolicy(frozenset({"fake.echo"})),
        session_factory=lambda config: session,
    )

    assert not registration.ok
    assert registration.error_code == "TRANSPORT_DISCONNECTED"
    assert registry.names == ("local",)
    assert safe_execute(local, {}, ToolContext(tmp_path)).ok
    assert session.closed
