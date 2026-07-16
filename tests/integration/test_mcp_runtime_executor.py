"""Runtime/Trace integration tests for registered MCP Tools."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from paperclaw.context.repository import SQLiteRepository
from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.mcp import (
    AllowListMCPPermissionPolicy,
    MCPInvocationResult,
    MCPServerConfig,
    connect_and_register_mcp_tools,
    normalize_tool_descriptor,
)
from paperclaw.tools.base import ToolContext, ToolResult, safe_execute
from paperclaw.tools.registry import ToolRegistry
from tests.helpers import FakeModel, action


class LocalTool:
    name = "local"
    description = "Local regression tool"

    def validate(self, arguments: dict[str, Any]) -> None:
        return None

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(True, "local-ok")


class TraceSession:
    def __init__(self, config: MCPServerConfig, secret: str) -> None:
        self.config = config
        self.secret = secret
        self.calls = 0
        self.closed = False
        self._descriptor = normalize_tool_descriptor(
            {
                "name": "echo",
                "description": "Echo one text value",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "minLength": 1}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
            server_id=config.server_id,
        )

    def connect(self) -> None:
        return None

    def initialize(self) -> object:
        return object()

    def discover(self):
        return (self._descriptor,)

    def call(self, request):
        self.calls += 1
        return MCPInvocationResult(
            server_id=self.config.server_id,
            tool_name=request.tool_name,
            request_id=self.calls,
            text_content=(f"{self.secret}:{request.arguments_dict()['text']}",),
            is_error=False,
        )

    def close(self) -> None:
        self.closed = True


def test_real_stdio_session_registers_and_invokes_fake_server(tmp_path: Path) -> None:
    server = Path(__file__).parents[1] / "fixtures" / "fake_mcp_server.py"
    config = MCPServerConfig(
        server_id="fixture",
        command=(sys.executable, str(server), "--mode", "normal"),
        request_timeout_seconds=1.0,
    )
    registry = ToolRegistry([LocalTool()])

    registration = connect_and_register_mcp_tools(
        registry,
        config,
        permission_policy=AllowListMCPPermissionPolicy(
            frozenset({"fixture.echo", "fixture.add"})
        ),
    )
    try:
        assert registration.ok
        assert registration.registered_tools == (
            "mcp.fixture.echo",
            "mcp.fixture.add",
        )
        echo = safe_execute(
            registry.get("mcp.fixture.echo"),
            {"text": "hello"},
            ToolContext(tmp_path),
        )
        add = safe_execute(
            registry.get("mcp.fixture.add"),
            {"a": 2, "b": 5},
            ToolContext(tmp_path),
        )
        local = safe_execute(registry.get("local"), {}, ToolContext(tmp_path))

        assert echo.ok and echo.output.startswith("hello")
        assert add.ok and add.output.startswith("7")
        assert local.ok and local.output == "local-ok"
    finally:
        if registration.connection is not None:
            registration.connection.close()


def test_mcp_calls_use_run_budget_and_existing_trace_fact_source(tmp_path: Path) -> None:
    secret = "trace-secret-value"
    config = MCPServerConfig(
        server_id="trace",
        command=("fake-server",),
        environment=(("TRACE_SECRET", secret),),
    )
    session = TraceSession(config, secret)
    registry = ToolRegistry([LocalTool()])
    registration = connect_and_register_mcp_tools(
        registry,
        config,
        permission_policy=AllowListMCPPermissionPolicy(frozenset({"trace.echo"})),
        session_factory=lambda current: session,
    )
    assert registration.ok

    repository = SQLiteRepository(tmp_path / "trace.db", migrate=True)
    events: list[tuple[str, dict]] = []
    try:
        engine = QueryEngine(
            AgentRuntimeExecutor(
                FakeModel(
                    [
                        action("mcp.trace.echo", {"text": "first"}),
                        action("mcp.trace.echo", {"text": "second"}),
                    ]
                ),
                tmp_path,
                registry=registry,
                repository=repository,
                enable_verification_gate=False,
            ),
            conversation_id="conv-mcp-budget",
            event_handler=lambda event_type, payload: events.append(
                (event_type, payload)
            ),
        )

        result = engine.submit(
            "invoke the remote tool twice",
            limits=RunLimits(max_steps=5, max_model_calls=5, max_tool_calls=1),
        )
        durable = repository.list_events(result.run_id)
        durable_json = json.dumps(
            [event.to_dict() for event in durable],
            ensure_ascii=False,
            sort_keys=True,
        )

        assert result.status == "budget_exhausted"
        assert result.stop_reason == "max_tool_calls"
        assert result.tool_calls == 1
        assert session.calls == 1
        assert any(
            event.event_type == "tool.started"
            and event.payload.get("tool") == "mcp.trace.echo"
            for event in durable
        )
        assert any(
            event.event_type == "tool.completed"
            and event.payload.get("tool") == "mcp.trace.echo"
            for event in durable
        )
        assert secret not in durable_json
        assert any(event_type == "tool.failed" for event_type, _ in events)
    finally:
        repository.close()
        if registration.connection is not None:
            registration.connection.close()
