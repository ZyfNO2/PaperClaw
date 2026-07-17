"""Normalized MCP contracts for PaperClaw v0.09 Phase A."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping

MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({MCP_PROTOCOL_VERSION})
DEFAULT_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
SERVER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class MCPConnectionState(str, Enum):
    """Observable lifecycle state for one client/server session."""

    NEW = "new"
    CONNECTED = "connected"
    INITIALIZED = "initialized"
    FAILED = "failed"
    CLOSED = "closed"


class MCPError(RuntimeError):
    """Structured and bounded error crossing the MCP protocol boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retriable: bool = False,
        server_id: str | None = None,
        request_id: int | str | None = None,
        rpc_code: int | None = None,
        phase: str | None = None,
    ) -> None:
        super().__init__(bounded_text(message, 500) or "MCP protocol error")
        self.code = require_text(code, "code", limit=100)
        self.retriable = retriable
        self.server_id = server_id
        self.request_id = request_id
        self.rpc_code = rpc_code
        self.phase = phase

    def with_context(
        self,
        *,
        server_id: str | None = None,
        request_id: int | str | None = None,
        phase: str | None = None,
    ) -> "MCPError":
        """Return a copy enriched with request context without mutating the error."""

        return MCPError(
            str(self),
            code=self.code,
            retriable=self.retriable,
            server_id=server_id if server_id is not None else self.server_id,
            request_id=request_id if request_id is not None else self.request_id,
            rpc_code=self.rpc_code,
            phase=phase if phase is not None else self.phase,
        )

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "mcp_error_code": self.code,
            "retriable": self.retriable,
        }
        if self.server_id:
            metadata["server_id"] = self.server_id
        if self.request_id is not None:
            metadata["request_id"] = self.request_id
        if self.rpc_code is not None:
            metadata["rpc_code"] = self.rpc_code
        if self.phase:
            metadata["phase"] = self.phase
        return metadata


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for the Phase A local stdio transport baseline.

    Environment values are used for subprocess launch but excluded from the
    fingerprint so low-entropy secrets are not hashed into durable metadata.
    """

    server_id: str
    command: tuple[str, ...]
    cwd: str | None = None
    environment: tuple[tuple[str, str], ...] = ()
    transport: str = "stdio"
    protocol_version: str = MCP_PROTOCOL_VERSION
    request_timeout_seconds: float = 10.0
    close_timeout_seconds: float = 2.0
    max_message_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        validate_server_id(self.server_id)
        if self.transport != "stdio":
            raise ValueError("Phase A supports only the stdio transport")
        if not isinstance(self.command, tuple) or not self.command:
            raise ValueError("command must be a non-empty tuple")
        if any(
            not isinstance(part, str) or not part or "\x00" in part
            for part in self.command
        ):
            raise ValueError("command entries must be non-empty strings without NUL")
        if self.cwd is not None and (
            not isinstance(self.cwd, str) or not self.cwd or "\x00" in self.cwd
        ):
            raise ValueError("cwd must be a non-empty string without NUL")
        if not isinstance(self.environment, tuple):
            raise ValueError("environment must be a tuple of key/value tuples")
        seen: set[str] = set()
        for item in self.environment:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("environment entries must be two-item tuples")
            key, value = item
            if (
                not isinstance(key, str)
                or not key
                or any(character in key for character in "=\x00\r\n")
            ):
                raise ValueError(
                    "environment keys must be valid process variable names"
                )
            if key in seen:
                raise ValueError(f"duplicate environment key: {key}")
            seen.add(key)
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError("environment values must be strings without NUL")
        if self.protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ValueError(
                f"unsupported MCP protocol version: {self.protocol_version}"
            )
        for name, value in (
            ("request_timeout_seconds", self.request_timeout_seconds),
            ("close_timeout_seconds", self.close_timeout_seconds),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value <= 300
            ):
                raise ValueError(f"{name} must be a finite number in (0, 300]")
        if (
            isinstance(self.max_message_bytes, bool)
            or not isinstance(self.max_message_bytes, int)
            or not 1_024 <= self.max_message_bytes <= 16_777_216
        ):
            raise ValueError("max_message_bytes must be an integer in [1024, 16777216]")

    @property
    def fingerprint(self) -> str:
        return sha256_json(
            {
                "server_id": self.server_id,
                "transport": self.transport,
                "command": list(self.command),
                "cwd": self.cwd,
                "environment_keys": sorted(key for key, _ in self.environment),
                "protocol_version": self.protocol_version,
                "request_timeout_seconds": float(self.request_timeout_seconds),
                "close_timeout_seconds": float(self.close_timeout_seconds),
                "max_message_bytes": self.max_message_bytes,
            }
        )


@dataclass(frozen=True)
class MCPServerIdentity:
    """Server implementation identity established by ``initialize``."""

    server_id: str
    name: str
    version: str
    protocol_version: str
    config_fingerprint: str
    title: str | None = None

    def __post_init__(self) -> None:
        validate_server_id(self.server_id)
        require_text(self.name, "name", limit=500)
        require_text(self.version, "version", limit=500)
        if self.protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ValueError("protocol_version is unsupported")
        if not _SHA256_PATTERN.fullmatch(self.config_fingerprint):
            raise ValueError("config_fingerprint must be a lowercase SHA-256 digest")
        if self.title is not None:
            require_text(self.title, "title", limit=500)


@dataclass(frozen=True)
class MCPCapabilitySnapshot:
    """Negotiated capability snapshot without raw Server instructions."""

    identity: MCPServerIdentity
    capability_names: frozenset[str]
    supports_tools: bool
    tools_list_changed: bool
    server_instructions_ignored: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.capability_names, frozenset) or any(
            not isinstance(name, str) or not name for name in self.capability_names
        ):
            raise ValueError("capability_names must be non-empty strings")
        for name, value in (
            ("supports_tools", self.supports_tools),
            ("tools_list_changed", self.tools_list_changed),
            ("server_instructions_ignored", self.server_instructions_ignored),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True)
class MCPToolDescriptor:
    """Normalized, Server-scoped MCP Tool descriptor."""

    server_id: str
    name: str
    description: str
    input_schema: Mapping[str, Any]
    input_schema_hash: str
    title: str | None = None
    output_schema: Mapping[str, Any] | None = None
    output_schema_hash: str | None = None
    schema_dialect: str = DEFAULT_SCHEMA_URI

    def __post_init__(self) -> None:
        validate_server_id(self.server_id)
        validate_tool_name(self.name)
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")
        if self.title is not None:
            require_text(self.title, "title", limit=500)
        if not isinstance(self.input_schema, Mapping):
            raise ValueError("input_schema must be an object")
        if not _SHA256_PATTERN.fullmatch(self.input_schema_hash):
            raise ValueError("input_schema_hash must be a lowercase SHA-256 digest")
        if self.output_schema is None:
            if self.output_schema_hash is not None:
                raise ValueError("output_schema_hash requires output_schema")
        elif (
            not isinstance(self.output_schema, Mapping)
            or self.output_schema_hash is None
            or not _SHA256_PATTERN.fullmatch(self.output_schema_hash)
        ):
            raise ValueError("output_schema and output_schema_hash are inconsistent")

    @property
    def qualified_name(self) -> str:
        return f"{self.server_id}.{self.name}"

    def input_schema_dict(self) -> dict[str, Any]:
        return thaw_json(self.input_schema)

    def output_schema_dict(self) -> dict[str, Any] | None:
        return None if self.output_schema is None else thaw_json(self.output_schema)


@dataclass(frozen=True)
class MCPInvocationRequest:
    """One semantic Tool call request before JSON-RPC ID assignment."""

    server_id: str
    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        validate_server_id(self.server_id)
        validate_tool_name(self.tool_name)
        if not isinstance(self.arguments, Mapping):
            raise ValueError("arguments must be an object")
        normalized = normalize_json_value(dict(self.arguments), path="arguments")
        object.__setattr__(self, "arguments", freeze_json(normalized))
        if self.timeout_seconds is not None:
            value = self.timeout_seconds
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value <= 300
            ):
                raise ValueError("timeout_seconds must be a finite number in (0, 300]")

    def arguments_dict(self) -> dict[str, Any]:
        return thaw_json(self.arguments)


@dataclass(frozen=True)
class MCPInvocationResult:
    """Normalized text/object result accepted by the Phase A boundary."""

    server_id: str
    tool_name: str
    request_id: int
    text_content: tuple[str, ...]
    is_error: bool
    structured_content: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        validate_server_id(self.server_id)
        validate_tool_name(self.tool_name)
        if isinstance(self.request_id, bool) or not isinstance(self.request_id, int):
            raise ValueError("request_id must be an integer")
        if any(not isinstance(item, str) for item in self.text_content):
            raise ValueError("text_content must contain only strings")
        if not isinstance(self.is_error, bool):
            raise ValueError("is_error must be a boolean")
        if self.structured_content is not None and not isinstance(
            self.structured_content, Mapping
        ):
            raise ValueError("structured_content must be an object")

    def structured_content_dict(self) -> dict[str, Any] | None:
        if self.structured_content is None:
            return None
        return thaw_json(self.structured_content)


def validate_server_id(value: Any) -> None:
    if not isinstance(value, str) or not SERVER_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "server_id must contain 1-64 ASCII letters, digits, '.', '_', or '-'"
        )


def validate_tool_name(value: Any) -> None:
    if not isinstance(value, str) or not TOOL_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            "tool name must contain 1-128 ASCII letters, digits, '.', '_', or '-'"
        )


def require_text(value: Any, field_name: str, *, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return bounded_text(value, limit)


def bounded_text(value: str, limit: int = 500) -> str:
    sanitized = "".join(character if character >= " " else " " for character in value)
    return " ".join(sanitized.split())[:limit]


def normalize_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite number at {path}")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"object key must be a string at {path}")
            normalized[key] = normalize_json_value(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            normalize_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ValueError(f"unsupported JSON value at {path}: {type(value).__name__}")


def freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
