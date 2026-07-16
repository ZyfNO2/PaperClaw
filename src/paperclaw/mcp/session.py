"""Strict MCP client session lifecycle for PaperClaw v0.09 Phase A."""

from __future__ import annotations

from typing import Any, Mapping

from paperclaw.mcp.contracts import (
    MCPCapabilitySnapshot,
    MCPConnectionState,
    MCPError,
    MCPInvocationRequest,
    MCPInvocationResult,
    MCPServerConfig,
    MCPServerIdentity,
    MCPToolDescriptor,
    SUPPORTED_PROTOCOL_VERSIONS,
    bounded_text,
    freeze_json,
    normalize_json_value,
    require_text,
)
from paperclaw.mcp.schema import normalize_tool_descriptor
from paperclaw.mcp.transport import MCPTransport, StdioMCPTransport

_TRANSPORT_TERMINAL_ERRORS = frozenset(
    {
        "REQUEST_TIMEOUT",
        "TRANSPORT_DISCONNECTED",
        "INVALID_JSON",
        "INVALID_RESPONSE",
        "MISMATCHED_RESPONSE_ID",
        "MESSAGE_TOO_LARGE",
    }
)
_PROTOCOL_TERMINAL_ERRORS = frozenset(
    {"INVALID_RESPONSE", "INVALID_TOOL_RESULT", "UNSUPPORTED_RESULT_CONTENT"}
)


class MCPClientSession:
    """Connect, initialize, discover, call, and close one MCP Server."""

    def __init__(
        self,
        config: MCPServerConfig,
        *,
        transport: MCPTransport | None = None,
        client_name: str = "paperclaw",
        client_version: str = "0.09-phase-a",
    ) -> None:
        self.config = config
        self._transport = transport or StdioMCPTransport(config)
        self._client_name = require_text(client_name, "client_name", limit=128)
        self._client_version = require_text(client_version, "client_version", limit=128)
        self._state = MCPConnectionState.NEW
        self._next_request_id = 1
        self._capabilities: MCPCapabilitySnapshot | None = None
        self._tools: dict[str, MCPToolDescriptor] = {}

    @property
    def state(self) -> MCPConnectionState:
        return self._state

    @property
    def capabilities(self) -> MCPCapabilitySnapshot | None:
        return self._capabilities

    @property
    def discovered_tools(self) -> tuple[MCPToolDescriptor, ...]:
        return tuple(self._tools.values())

    def connect(self) -> None:
        self._require_state(MCPConnectionState.NEW, "connect")
        try:
            self._transport.connect()
        except MCPError:
            self._state = MCPConnectionState.FAILED
            raise
        self._state = MCPConnectionState.CONNECTED

    def initialize(self) -> MCPCapabilitySnapshot:
        self._require_state(MCPConnectionState.CONNECTED, "initialize")
        request_id = self._allocate_request_id()
        try:
            result = self._transport.request(
                request_id,
                "initialize",
                {
                    "protocolVersion": self.config.protocol_version,
                    "capabilities": {},
                    "clientInfo": {
                        "name": self._client_name,
                        "version": self._client_version,
                    },
                },
                timeout_seconds=self.config.request_timeout_seconds,
                cancel_on_timeout=False,
            )
            snapshot = self._normalize_initialize_result(result, request_id)
            self._transport.notify("notifications/initialized")
        except MCPError:
            self._state = MCPConnectionState.FAILED
            self._best_effort_close()
            raise
        self._capabilities = snapshot
        self._state = MCPConnectionState.INITIALIZED
        return snapshot

    def discover(self) -> tuple[MCPToolDescriptor, ...]:
        self._require_state(MCPConnectionState.INITIALIZED, "discover")
        if self._capabilities is None or not self._capabilities.supports_tools:
            raise MCPError(
                "MCP Server did not negotiate the tools capability",
                code="REQUIRED_CAPABILITY_MISSING",
                server_id=self.config.server_id,
                phase="tools/list",
            )
        cursor: str | None = None
        seen_cursors: set[str] = set()
        normalized: dict[str, MCPToolDescriptor] = {}
        for _ in range(100):
            request_id = self._allocate_request_id()
            try:
                result = self._transport.request(
                    request_id,
                    "tools/list",
                    None if cursor is None else {"cursor": cursor},
                    timeout_seconds=self.config.request_timeout_seconds,
                )
                next_cursor = self._normalize_tool_page(
                    result,
                    request_id=request_id,
                    target=normalized,
                )
            except MCPError as exc:
                enriched = exc.with_context(request_id=request_id, phase="tools/list")
                self._fail_if_terminal(enriched)
                raise enriched from exc
            if next_cursor is None:
                self._tools = normalized
                return tuple(normalized.values())
            if next_cursor in seen_cursors:
                error = MCPError(
                    "tools/list pagination cursor repeated",
                    code="INVALID_RESPONSE",
                    server_id=self.config.server_id,
                    request_id=request_id,
                    phase="tools/list",
                )
                self._fail_protocol(error)
                raise error
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        error = MCPError(
            "tools/list exceeded the 100-page safety limit",
            code="INVALID_RESPONSE",
            server_id=self.config.server_id,
            phase="tools/list",
        )
        self._fail_protocol(error)
        raise error

    def call(self, request: MCPInvocationRequest) -> MCPInvocationResult:
        self._require_state(MCPConnectionState.INITIALIZED, "call")
        if request.server_id != self.config.server_id:
            raise MCPError(
                "invocation server_id does not match the active session",
                code="SERVER_ID_MISMATCH",
                server_id=self.config.server_id,
                phase="tools/call",
            )
        if request.tool_name not in self._tools:
            raise MCPError(
                f"tool was not discovered in this session: {request.tool_name}",
                code="TOOL_NOT_DISCOVERED",
                server_id=self.config.server_id,
                phase="tools/call",
            )
        request_id = self._allocate_request_id()
        try:
            result = self._transport.request(
                request_id,
                "tools/call",
                {"name": request.tool_name, "arguments": request.arguments_dict()},
                timeout_seconds=(
                    request.timeout_seconds or self.config.request_timeout_seconds
                ),
            )
            return self._normalize_invocation_result(
                result,
                request_id=request_id,
                tool_name=request.tool_name,
            )
        except MCPError as exc:
            enriched = exc.with_context(request_id=request_id, phase="tools/call")
            self._fail_if_terminal(enriched)
            raise enriched from exc

    def close(self) -> None:
        if self._state is MCPConnectionState.CLOSED:
            return
        try:
            self._transport.close()
        finally:
            self._state = MCPConnectionState.CLOSED
            self._tools = {}

    def __enter__(self) -> "MCPClientSession":
        self.connect()
        self.initialize()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _normalize_initialize_result(
        self, result: Any, request_id: int
    ) -> MCPCapabilitySnapshot:
        if not isinstance(result, Mapping):
            raise self._response_error(
                "initialize result must be an object", request_id, "initialize"
            )
        protocol_version = result.get("protocolVersion")
        if (
            protocol_version not in SUPPORTED_PROTOCOL_VERSIONS
            or protocol_version != self.config.protocol_version
        ):
            raise MCPError(
                f"Server selected unsupported protocol version: {protocol_version}",
                code="PROTOCOL_VERSION_MISMATCH",
                server_id=self.config.server_id,
                request_id=request_id,
                phase="initialize",
            )
        capabilities = result.get("capabilities")
        server_info = result.get("serverInfo")
        if not isinstance(capabilities, Mapping):
            raise self._response_error(
                "initialize capabilities must be an object", request_id, "initialize"
            )
        if not isinstance(server_info, Mapping):
            raise self._response_error(
                "initialize serverInfo must be an object", request_id, "initialize"
            )
        tools = capabilities.get("tools")
        if tools is not None and not isinstance(tools, Mapping):
            raise self._response_error(
                "tools capability must be an object", request_id, "initialize"
            )
        list_changed = False
        if isinstance(tools, Mapping):
            list_changed = tools.get("listChanged", False)
            if not isinstance(list_changed, bool):
                raise self._response_error(
                    "tools.listChanged must be a boolean", request_id, "initialize"
                )
        identity = MCPServerIdentity(
            server_id=self.config.server_id,
            name=self._response_text(
                server_info.get("name"), "serverInfo.name", request_id, "initialize"
            ),
            version=self._response_text(
                server_info.get("version"),
                "serverInfo.version",
                request_id,
                "initialize",
            ),
            title=self._optional_response_text(
                server_info.get("title"), "serverInfo.title", request_id, "initialize"
            ),
            protocol_version=protocol_version,
            config_fingerprint=self.config.fingerprint,
        )
        return MCPCapabilitySnapshot(
            identity=identity,
            capability_names=frozenset(str(key) for key in capabilities),
            supports_tools=isinstance(tools, Mapping),
            tools_list_changed=list_changed,
            server_instructions_ignored=result.get("instructions") is not None,
        )

    def _normalize_tool_page(
        self,
        result: Any,
        *,
        request_id: int,
        target: dict[str, MCPToolDescriptor],
    ) -> str | None:
        if not isinstance(result, Mapping):
            raise self._response_error(
                "tools/list result must be an object", request_id, "tools/list"
            )
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise self._response_error(
                "tools/list result must contain a tools array", request_id, "tools/list"
            )
        page: list[MCPToolDescriptor] = []
        page_names: set[str] = set()
        for raw_tool in tools:
            descriptor = normalize_tool_descriptor(
                raw_tool, server_id=self.config.server_id
            )
            if descriptor.name in target or descriptor.name in page_names:
                raise MCPError(
                    f"duplicate MCP tool name: {descriptor.name}",
                    code="INVALID_TOOL_SCHEMA",
                    server_id=self.config.server_id,
                    request_id=request_id,
                    phase="tools/list",
                )
            page.append(descriptor)
            page_names.add(descriptor.name)
        next_cursor = result.get("nextCursor")
        if next_cursor is not None and (
            not isinstance(next_cursor, str) or not next_cursor
        ):
            raise self._response_error(
                "tools/list nextCursor must be a non-empty string",
                request_id,
                "tools/list",
            )
        for descriptor in page:
            target[descriptor.name] = descriptor
        return next_cursor

    def _normalize_invocation_result(
        self,
        result: Any,
        *,
        request_id: int,
        tool_name: str,
    ) -> MCPInvocationResult:
        if not isinstance(result, Mapping):
            raise self._tool_result_error(
                "tools/call result must be an object", request_id
            )
        content = result.get("content")
        if not isinstance(content, list):
            raise self._tool_result_error(
                "tools/call content must be an array", request_id
            )
        text_content: list[str] = []
        for index, item in enumerate(content):
            if not isinstance(item, Mapping):
                raise self._tool_result_error(
                    f"content[{index}] must be an object", request_id
                )
            if item.get("type") != "text":
                raise MCPError(
                    f"unsupported tools/call content type: {item.get('type')}",
                    code="UNSUPPORTED_RESULT_CONTENT",
                    server_id=self.config.server_id,
                    request_id=request_id,
                    phase="tools/call",
                )
            text = item.get("text")
            if not isinstance(text, str):
                raise self._tool_result_error(
                    f"content[{index}].text must be a string", request_id
                )
            text_content.append(text)
        is_error = result.get("isError", False)
        if not isinstance(is_error, bool):
            raise self._tool_result_error(
                "tools/call isError must be a boolean", request_id
            )
        structured = result.get("structuredContent")
        frozen_structured: Mapping[str, Any] | None = None
        if structured is not None:
            if not isinstance(structured, Mapping):
                raise self._tool_result_error(
                    "structuredContent must be an object", request_id
                )
            try:
                frozen_structured = freeze_json(
                    normalize_json_value(dict(structured), path="structuredContent")
                )
            except ValueError as exc:
                raise self._tool_result_error(str(exc), request_id) from exc
        return MCPInvocationResult(
            server_id=self.config.server_id,
            tool_name=tool_name,
            request_id=request_id,
            text_content=tuple(text_content),
            is_error=is_error,
            structured_content=frozen_structured,
        )

    def _require_state(self, expected: MCPConnectionState, operation: str) -> None:
        if self._state is not expected:
            raise MCPError(
                f"{operation} requires state {expected.value}; current state is {self._state.value}",
                code="INVALID_STATE",
                server_id=self.config.server_id,
                phase=operation,
            )

    def _allocate_request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id

    def _fail_if_terminal(self, error: MCPError) -> None:
        if (
            error.code in _TRANSPORT_TERMINAL_ERRORS
            or error.code in _PROTOCOL_TERMINAL_ERRORS
        ):
            self._state = MCPConnectionState.FAILED
            self._best_effort_close()

    def _fail_protocol(self, error: MCPError) -> None:
        self._state = MCPConnectionState.FAILED
        self._best_effort_close()

    def _best_effort_close(self) -> None:
        try:
            self._transport.close()
        except MCPError:
            pass

    def _response_error(self, message: str, request_id: int, phase: str) -> MCPError:
        return MCPError(
            message,
            code="INVALID_RESPONSE",
            server_id=self.config.server_id,
            request_id=request_id,
            phase=phase,
        )

    def _tool_result_error(self, message: str, request_id: int) -> MCPError:
        return MCPError(
            message,
            code="INVALID_TOOL_RESULT",
            server_id=self.config.server_id,
            request_id=request_id,
            phase="tools/call",
        )

    def _response_text(
        self, value: Any, field: str, request_id: int, phase: str
    ) -> str:
        if not isinstance(value, str) or not value.strip():
            raise self._response_error(
                f"{field} must be a non-empty string", request_id, phase
            )
        return bounded_text(value, 500)

    def _optional_response_text(
        self, value: Any, field: str, request_id: int, phase: str
    ) -> str | None:
        if value is None:
            return None
        return self._response_text(value, field, request_id, phase)
