"""Local stdio JSON-RPC transport baseline for MCP Phase A."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any, Mapping, Protocol

from paperclaw.mcp.contracts import (
    MCPError,
    MCPServerConfig,
    bounded_text,
    freeze_json,
    normalize_json_value,
    thaw_json,
)

_EOF = object()


class MCPTransport(Protocol):
    """Minimal transport contract consumed by ``MCPClientSession``."""

    def connect(self) -> None: ...

    def request(
        self,
        request_id: int,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        timeout_seconds: float,
        cancel_on_timeout: bool = True,
    ) -> Any: ...

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None: ...

    def close(self) -> None: ...


class StdioMCPTransport:
    """Synchronous, single-flight, newline-delimited stdio transport."""

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._messages: queue.Queue[object] = queue.Queue()
        self._write_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._closed = False

    def connect(self) -> None:
        if self._process is not None or self._closed:
            raise self._error(
                "transport cannot connect from its current state",
                "INVALID_STATE",
                "connect",
            )
        environment = os.environ.copy()
        environment.update(dict(self._config.environment))
        try:
            self._process = subprocess.Popen(
                self._config.command,
                cwd=self._config.cwd,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except (OSError, ValueError) as exc:
            raise self._error(
                f"failed to start MCP server: {type(exc).__name__}",
                "TRANSPORT_START_FAILED",
                "connect",
            ) from exc
        self._reader = threading.Thread(
            target=self._read_stdout,
            name=f"paperclaw-mcp-{self._config.server_id}",
            daemon=True,
        )
        self._reader.start()

    def request(
        self,
        request_id: int,
        method: str,
        params: Mapping[str, Any] | None,
        *,
        timeout_seconds: float,
        cancel_on_timeout: bool = True,
    ) -> Any:
        with self._request_lock:
            self._ensure_running(method)
            message: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params is not None:
                try:
                    normalized = normalize_json_value(dict(params), path="params")
                except ValueError as exc:
                    raise self._error(str(exc), "INVALID_REQUEST", method) from exc
                message["params"] = thaw_json(freeze_json(normalized))
            self._write_message(message, phase=method)
            return self._read_response(
                request_id,
                method,
                timeout_seconds=timeout_seconds,
                cancel_on_timeout=cancel_on_timeout,
            )

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        self._ensure_running(method)
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            try:
                message["params"] = normalize_json_value(dict(params), path="params")
            except ValueError as exc:
                raise self._error(str(exc), "INVALID_REQUEST", method) from exc
        self._write_message(message, phase=method)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=self._config.close_timeout_seconds)
            return
        except subprocess.TimeoutExpired:
            process.terminate()
        try:
            process.wait(timeout=self._config.close_timeout_seconds)
            return
        except subprocess.TimeoutExpired:
            process.kill()
        try:
            process.wait(timeout=self._config.close_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise self._error(
                "MCP server did not exit after kill", "CLOSE_FAILED", "close"
            ) from exc

    def _read_response(
        self,
        request_id: int,
        method: str,
        *,
        timeout_seconds: float,
        cancel_on_timeout: bool,
    ) -> Any:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._handle_timeout(request_id, method, cancel_on_timeout)
            try:
                item = self._messages.get(timeout=max(0.001, remaining))
            except queue.Empty:
                self._handle_timeout(request_id, method, cancel_on_timeout)
            if item is _EOF:
                raise self._error(
                    "MCP server disconnected before responding",
                    "TRANSPORT_DISCONNECTED",
                    method,
                    request_id=request_id,
                    retriable=True,
                )
            if isinstance(item, MCPError):
                raise item.with_context(request_id=request_id, phase=method)
            if not isinstance(item, Mapping):
                raise self._error(
                    "MCP response is not an object",
                    "INVALID_RESPONSE",
                    method,
                    request_id=request_id,
                )
            if "method" in item and "id" not in item:
                continue
            return self._validate_response(item, request_id=request_id, method=method)

    def _validate_response(
        self,
        item: Mapping[str, Any],
        *,
        request_id: int,
        method: str,
    ) -> Any:
        if item.get("id") != request_id:
            raise self._error(
                "MCP response ID does not match the active request",
                "MISMATCHED_RESPONSE_ID",
                method,
                request_id=request_id,
            )
        if item.get("jsonrpc") != "2.0":
            raise self._error(
                "MCP response has an invalid jsonrpc version",
                "INVALID_RESPONSE",
                method,
                request_id=request_id,
            )
        has_result = "result" in item
        has_error = "error" in item
        if has_result == has_error:
            raise self._error(
                "MCP response must contain exactly one of result or error",
                "INVALID_RESPONSE",
                method,
                request_id=request_id,
            )
        if has_result:
            return item["result"]
        error = item.get("error")
        if not isinstance(error, Mapping):
            raise self._error(
                "MCP protocol error payload is invalid",
                "INVALID_RESPONSE",
                method,
                request_id=request_id,
            )
        rpc_code = error.get("code")
        message = error.get("message")
        if isinstance(rpc_code, bool) or not isinstance(rpc_code, int):
            raise self._error(
                "MCP protocol error code is invalid",
                "INVALID_RESPONSE",
                method,
                request_id=request_id,
            )
        if not isinstance(message, str) or not message.strip():
            raise self._error(
                "MCP protocol error message is invalid",
                "INVALID_RESPONSE",
                method,
                request_id=request_id,
            )
        raise MCPError(
            f"MCP server rejected {method}: {bounded_text(message, 200)}",
            code="PROTOCOL_ERROR",
            retriable=rpc_code in {-32000, -32001, -32002},
            server_id=self._config.server_id,
            request_id=request_id,
            rpc_code=rpc_code,
            phase=method,
        )

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._messages.put(_EOF)
            return
        try:
            while True:
                line = process.stdout.readline(self._config.max_message_bytes + 1)
                if not line:
                    self._messages.put(_EOF)
                    return
                if len(line) > self._config.max_message_bytes:
                    self._messages.put(
                        self._error(
                            "MCP response exceeds max_message_bytes",
                            "MESSAGE_TOO_LARGE",
                            None,
                        )
                    )
                    return
                payload = line[:-1] if line.endswith(b"\n") else line
                if payload.endswith(b"\r"):
                    payload = payload[:-1]
                if b"\n" in payload or b"\r" in payload:
                    self._messages.put(
                        self._error(
                            "MCP stdio response contains an embedded newline",
                            "INVALID_RESPONSE",
                            None,
                        )
                    )
                    return
                try:
                    decoded = json.loads(payload.decode("utf-8"))
                except UnicodeDecodeError:
                    self._messages.put(
                        self._error(
                            "MCP response is not valid UTF-8", "INVALID_RESPONSE", None
                        )
                    )
                    return
                except json.JSONDecodeError:
                    self._messages.put(
                        self._error(
                            "MCP response is not valid JSON", "INVALID_JSON", None
                        )
                    )
                    return
                self._messages.put(decoded)
        except OSError:
            self._messages.put(_EOF)

    def _write_message(self, message: Mapping[str, Any], *, phase: str) -> None:
        payload = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(payload) + 1 > self._config.max_message_bytes:
            raise self._error(
                "MCP request exceeds max_message_bytes", "MESSAGE_TOO_LARGE", phase
            )
        process = self._process
        if process is None or process.stdin is None:
            raise self._error(
                "MCP transport is not connected",
                "TRANSPORT_DISCONNECTED",
                phase,
                retriable=True,
            )
        with self._write_lock:
            try:
                process.stdin.write(payload + b"\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise self._error(
                    "MCP server disconnected while writing a request",
                    "TRANSPORT_DISCONNECTED",
                    phase,
                    retriable=True,
                ) from exc

    def _handle_timeout(
        self, request_id: int, method: str, cancel_on_timeout: bool
    ) -> None:
        if cancel_on_timeout:
            try:
                self.notify(
                    "notifications/cancelled",
                    {"requestId": request_id, "reason": "PaperClaw request timeout"},
                )
            except MCPError:
                pass
        raise self._error(
            f"MCP request timed out: {method}",
            "REQUEST_TIMEOUT",
            method,
            request_id=request_id,
            retriable=True,
        )

    def _ensure_running(self, phase: str) -> None:
        process = self._process
        if self._closed or process is None or process.poll() is not None:
            raise self._error(
                "MCP transport is not connected",
                "TRANSPORT_DISCONNECTED",
                phase,
                retriable=True,
            )

    def _error(
        self,
        message: str,
        code: str,
        phase: str | None,
        *,
        request_id: int | None = None,
        retriable: bool = False,
    ) -> MCPError:
        return MCPError(
            message,
            code=code,
            retriable=retriable,
            server_id=self._config.server_id,
            request_id=request_id,
            phase=phase,
        )
