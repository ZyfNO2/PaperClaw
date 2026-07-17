from __future__ import annotations

from pathlib import Path
import sys
import time

import pytest

from paperclaw.mcp import (
    MCPClientSession,
    MCPConnectionState,
    MCPError,
    MCPInvocationRequest,
    MCPServerConfig,
    normalize_tool_descriptor,
)

FAKE_SERVER = Path(__file__).parents[1] / "fixtures" / "fake_mcp_server.py"


def _config(
    mode: str = "normal",
    *,
    timeout: float = 3.0,
    environment: tuple[tuple[str, str], ...] = (),
) -> MCPServerConfig:
    return MCPServerConfig(
        server_id="local-test",
        command=(sys.executable, "-u", str(FAKE_SERVER), "--mode", mode),
        environment=environment,
        request_timeout_seconds=timeout,
        close_timeout_seconds=0.25,
    )


def _initialized_session(
    mode: str = "normal", *, timeout: float = 3.0
) -> MCPClientSession:
    session = MCPClientSession(_config(mode, timeout=timeout))
    session.connect()
    session.initialize()
    return session


def test_lifecycle_discovers_normalizes_calls_and_closes() -> None:
    session = MCPClientSession(_config())
    assert session.state is MCPConnectionState.NEW

    session.connect()
    assert session.state is MCPConnectionState.CONNECTED

    capabilities = session.initialize()
    assert session.state is MCPConnectionState.INITIALIZED
    assert capabilities.identity.server_id == "local-test"
    assert capabilities.identity.name == "paperclaw-fake-mcp"
    assert capabilities.supports_tools is True
    assert capabilities.tools_list_changed is False
    assert capabilities.server_instructions_ignored is True

    tools = session.discover()
    assert [tool.name for tool in tools] == ["echo", "add"]
    assert [tool.qualified_name for tool in tools] == [
        "local-test.echo",
        "local-test.add",
    ]
    assert tools[0].input_schema_dict() == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "description": "Echo input",
        "properties": {"text": {"minLength": 1, "type": "string"}},
        "required": ["text"],
        "type": "object",
    }
    assert len(tools[0].input_schema_hash) == 64

    result = session.call(
        MCPInvocationRequest(
            server_id="local-test",
            tool_name="echo",
            arguments={"text": "hello"},
        )
    )
    assert result.text_content == ("hello",)
    assert result.is_error is False
    assert result.structured_content_dict() == {"echoed": "hello"}

    session.close()
    assert session.state is MCPConnectionState.CLOSED
    session.close()


def test_call_requires_successful_discovery() -> None:
    session = _initialized_session()
    try:
        with pytest.raises(MCPError) as raised:
            session.call(
                MCPInvocationRequest(
                    server_id="local-test", tool_name="echo", arguments={"text": "x"}
                )
            )
        assert raised.value.code == "TOOL_NOT_DISCOVERED"
        assert session.state is MCPConnectionState.INITIALIZED
    finally:
        session.close()


def test_unsupported_schema_fails_closed_without_registering_tool() -> None:
    session = _initialized_session("unsupported_schema")
    try:
        with pytest.raises(MCPError) as raised:
            session.discover()
        assert raised.value.code == "UNSUPPORTED_TOOL_SCHEMA"
        assert session.discovered_tools == ()

        with pytest.raises(MCPError) as call_raised:
            session.call(
                MCPInvocationRequest(
                    server_id="local-test",
                    tool_name="unsafe_union",
                    arguments={"a": "x"},
                )
            )
        assert call_raised.value.code == "TOOL_NOT_DISCOVERED"
    finally:
        session.close()


def test_timeout_marks_session_failed_and_is_bounded() -> None:
    session = _initialized_session("timeout_call")
    session.discover()
    started = time.monotonic()
    with pytest.raises(MCPError) as raised:
        session.call(
            MCPInvocationRequest(
                server_id="local-test",
                tool_name="echo",
                arguments={"text": "slow"},
                timeout_seconds=0.15,
            )
        )
    elapsed = time.monotonic() - started

    assert raised.value.code == "REQUEST_TIMEOUT"
    assert raised.value.retriable is True
    assert elapsed < 2.0
    assert session.state is MCPConnectionState.FAILED
    session.close()


def test_disconnect_marks_session_failed() -> None:
    session = _initialized_session("disconnect_call")
    session.discover()
    with pytest.raises(MCPError) as raised:
        session.call(
            MCPInvocationRequest(
                server_id="local-test",
                tool_name="echo",
                arguments={"text": "disconnect"},
            )
        )
    assert raised.value.code == "TRANSPORT_DISCONNECTED"
    assert session.state is MCPConnectionState.FAILED
    session.close()


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("invalid_json_list", "INVALID_JSON"),
        ("wrong_id_list", "MISMATCHED_RESPONSE_ID"),
        ("invalid_response_list", "INVALID_RESPONSE"),
    ],
)
def test_invalid_transport_responses_fail_session(
    mode: str, expected_code: str
) -> None:
    session = _initialized_session(mode)
    with pytest.raises(MCPError) as raised:
        session.discover()
    assert raised.value.code == expected_code
    assert session.state is MCPConnectionState.FAILED
    session.close()


def test_invalid_tool_result_fails_session() -> None:
    session = _initialized_session("invalid_tool_result")
    session.discover()
    with pytest.raises(MCPError) as raised:
        session.call(
            MCPInvocationRequest(
                server_id="local-test",
                tool_name="echo",
                arguments={"text": "x"},
            )
        )
    assert raised.value.code == "UNSUPPORTED_RESULT_CONTENT"
    assert session.state is MCPConnectionState.FAILED
    session.close()


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("protocol_mismatch", "PROTOCOL_VERSION_MISMATCH"),
        ("invalid_initialize", "INVALID_RESPONSE"),
        ("disconnect_initialize", "TRANSPORT_DISCONNECTED"),
    ],
)
def test_initialize_failures_close_transport(mode: str, expected_code: str) -> None:
    session = MCPClientSession(_config(mode, timeout=2.0))
    session.connect()
    with pytest.raises(MCPError) as raised:
        session.initialize()
    assert raised.value.code == expected_code
    assert session.state is MCPConnectionState.FAILED
    session.close()


def test_lifecycle_rejects_out_of_order_operations() -> None:
    session = MCPClientSession(_config())
    with pytest.raises(MCPError) as raised:
        session.initialize()
    assert raised.value.code == "INVALID_STATE"
    assert session.state is MCPConnectionState.NEW
    session.close()


def test_config_fingerprint_excludes_environment_values() -> None:
    first = _config(environment=(("TOKEN", "secret-one"),))
    second = _config(environment=(("TOKEN", "secret-two"),))
    assert first.fingerprint == second.fingerprint
    assert "secret-one" not in first.fingerprint


def test_normalization_is_deterministic_and_immutable() -> None:
    first = normalize_tool_descriptor(
        {
            "name": "sample",
            "description": "sample",
            "inputSchema": {
                "required": ["b", "a"],
                "properties": {
                    "b": {"type": "integer"},
                    "a": {"type": "string"},
                },
                "type": "object",
            },
        },
        server_id="local-test",
    )
    second = normalize_tool_descriptor(
        {
            "inputSchema": {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
            "description": "sample",
            "name": "sample",
        },
        server_id="local-test",
    )
    assert first.input_schema_hash == second.input_schema_hash
    assert first.input_schema_dict() == second.input_schema_dict()
    with pytest.raises(TypeError):
        first.input_schema["type"] = "string"  # type: ignore[index]


def test_schema_non_finite_value_is_structured_error() -> None:
    with pytest.raises(MCPError) as raised:
        normalize_tool_descriptor(
            {
                "name": "bad_default",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number", "default": float("nan")}
                    },
                },
            },
            server_id="local-test",
        )
    assert raised.value.code == "INVALID_TOOL_SCHEMA"
