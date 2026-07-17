from __future__ import annotations

from pathlib import Path
import sys
import threading
import time

import pytest

from paperclaw.mcp import (
    MCPClientSession,
    MCPConnectionState,
    MCPError,
    MCPInvocationRequest,
    MCPServerConfig,
)
from paperclaw.mcp.transport import StdioMCPTransport

HARDENING_SERVER = (
    Path(__file__).parents[1] / "fixtures" / "fake_mcp_hardening_server.py"
)


def _config(
    mode: str,
    *,
    request_timeout: float = 0.5,
    close_timeout: float = 0.1,
    max_message_bytes: int = 4096,
) -> MCPServerConfig:
    return MCPServerConfig(
        server_id="hardening-test",
        command=(sys.executable, "-u", str(HARDENING_SERVER), "--mode", mode),
        request_timeout_seconds=request_timeout,
        close_timeout_seconds=close_timeout,
        max_message_bytes=max_message_bytes,
    )


def _initialized_session(mode: str, **config: object) -> MCPClientSession:
    session = MCPClientSession(_config(mode, **config))  # type: ignore[arg-type]
    session.connect()
    session.initialize()
    return session


def test_oversized_response_without_newline_is_rejected_before_timeout() -> None:
    session = _initialized_session(
        "oversized_no_newline",
        request_timeout=1.0,
        max_message_bytes=1024,
    )
    started = time.monotonic()
    with pytest.raises(MCPError) as raised:
        session.discover()
    elapsed = time.monotonic() - started

    assert raised.value.code == "MESSAGE_TOO_LARGE"
    assert session.state is MCPConnectionState.FAILED
    assert elapsed < 1.0
    session.close()


def test_stderr_flood_cannot_block_protocol_stdout() -> None:
    started = time.monotonic()
    session = _initialized_session("stderr_flood", request_timeout=2.0)
    try:
        tools = session.discover()
        assert [tool.name for tool in tools] == ["echo"]
        assert time.monotonic() - started < 2.0
    finally:
        session.close()


def test_timeout_is_terminal_and_late_response_is_not_reused() -> None:
    session = _initialized_session("late_call", request_timeout=0.5)
    session.discover()

    with pytest.raises(MCPError) as raised:
        session.call(
            MCPInvocationRequest(
                server_id="hardening-test",
                tool_name="echo",
                arguments={"text": "late"},
                timeout_seconds=0.05,
            )
        )
    assert raised.value.code == "REQUEST_TIMEOUT"
    assert session.state is MCPConnectionState.FAILED

    with pytest.raises(MCPError) as reused:
        session.call(
            MCPInvocationRequest(
                server_id="hardening-test",
                tool_name="echo",
                arguments={"text": "must-not-run"},
            )
        )
    assert reused.value.code == "INVALID_STATE"
    session.close()


def test_close_while_read_is_blocked_is_bounded_and_reclaims_request_thread() -> None:
    transport = StdioMCPTransport(
        _config("block_initialize", request_timeout=5.0, close_timeout=0.05)
    )
    errors: list[BaseException] = []
    transport.connect()

    def request() -> None:
        try:
            transport.request(
                1,
                "initialize",
                {"protocolVersion": "2025-11-25"},
                timeout_seconds=5.0,
                cancel_on_timeout=False,
            )
        except BaseException as exc:  # test thread must report every exit path
            errors.append(exc)

    worker = threading.Thread(target=request, daemon=True)
    worker.start()
    time.sleep(0.05)

    started = time.monotonic()
    transport.close()
    elapsed = time.monotonic() - started
    worker.join(timeout=1.0)

    assert elapsed < 1.0
    assert not worker.is_alive()
    assert errors
    assert isinstance(errors[0], MCPError)
    assert errors[0].code in {"TRANSPORT_DISCONNECTED", "REQUEST_TIMEOUT"}


def test_pagination_loop_fails_closed_without_partial_discovery() -> None:
    session = _initialized_session("pagination_loop")
    with pytest.raises(MCPError) as raised:
        session.discover()

    assert raised.value.code == "INVALID_RESPONSE"
    assert session.state is MCPConnectionState.FAILED
    assert session.discovered_tools == ()
    session.close()


def test_duplicate_tool_across_pages_is_atomic() -> None:
    session = _initialized_session("duplicate_tool")
    try:
        with pytest.raises(MCPError) as raised:
            session.discover()
        assert raised.value.code == "INVALID_TOOL_SCHEMA"
        assert session.discovered_tools == ()
    finally:
        session.close()


def test_deep_but_bounded_json_does_not_crash_reader_thread() -> None:
    session = _initialized_session(
        "deep_json",
        request_timeout=2.0,
        max_message_bytes=16_384,
    )
    try:
        assert session.discover() == ()
        assert session.state is MCPConnectionState.INITIALIZED
    finally:
        session.close()
