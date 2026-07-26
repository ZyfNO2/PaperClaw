from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.projects.extension_execution import (
    ConnectorCallResult,
    ConnectorInvocationError,
    MappingProjectSecretResolver,
    ProjectExtensionExecutor,
)
from paperclaw.projects.extension_runtime import ProjectExtensionActivator
from paperclaw.projects.extensions import (
    ExtensionPermissions,
    ProjectExtensionDescriptor,
    ProjectExtensionRegistry,
)
from paperclaw.projects.manifest import ProjectManifestStore
from paperclaw.tools.base import ToolContext, safe_execute
from paperclaw.tools.registry import ToolRegistry


SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
    "additionalProperties": False,
}


class Runtime:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = []
        self.closed = False

    def discover_tools(self):
        return [{"name": "search", "input_schema": SCHEMA}]

    def call_tool(self, name, arguments, context):
        self.calls.append((name, arguments, context))
        return self.outcome(name, arguments, context)

    def close(self) -> None:
        self.closed = True


def configured(tmp_path: Path, runtime: Runtime, resolver=None):
    ProjectManifestStore(tmp_path).initialize("Host Resolution Test")
    registry = ProjectExtensionRegistry(tmp_path)
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="connector.search",
            kind="connector",
            version="1.0.0",
            entrypoint="mcp:search",
            enabled=True,
            trust_source="verified",
            auth_ref="secret://project/search",
            permissions=ExtensionPermissions(tools=("search",)),
        )
    )
    activator = ProjectExtensionActivator(
        registry,
        permission_ceiling=ExtensionPermissions(tools=("search",)),
        connector_factories={"search": lambda *_: runtime},
    )
    executor = ProjectExtensionExecutor(activator, secret_resolver=resolver)
    tools = ToolRegistry()
    registration = executor.register_tools(tools)
    return registry, executor, tools.get(registration.registered_tools[0])


def test_host_value_is_resolved_redacted_and_not_audited(tmp_path: Path) -> None:
    host_value = "project-host-value-123"

    def outcome(name, arguments, context):
        assert name == "search"
        assert arguments == {"query": "evidence"}
        assert context.auth_value == host_value
        assert context.auth_ref == "secret://project/search"
        assert host_value not in repr(context)
        assert "auth_value" not in context.to_public_dict()
        result = ConnectorCallResult(
            True,
            f"found evidence with {host_value}",
            metadata={"session_marker": host_value, "extension_id": "spoofed"},
        )
        assert host_value not in repr(result)
        return result

    runtime = Runtime(outcome)
    registry, executor, tool = configured(
        tmp_path,
        runtime,
        MappingProjectSecretResolver({"secret://project/search": host_value}),
    )
    result = safe_execute(tool, {"query": "evidence"}, ToolContext(tmp_path))
    assert result.ok
    assert host_value not in result.output
    assert "<REDACTED>" in result.output
    assert result.metadata["session_marker"] == "<REDACTED>"
    assert result.metadata["extension_id"] == "connector.search"
    assert host_value.encode() not in registry.audit_path.read_bytes()
    executor.close()
    assert runtime.closed


def test_missing_host_value_fails_before_runtime_call(tmp_path: Path) -> None:
    runtime = Runtime(lambda *_: ConnectorCallResult(True, "unexpected"))
    registry, executor, tool = configured(
        tmp_path,
        runtime,
        MappingProjectSecretResolver({}),
    )
    result = safe_execute(tool, {"query": "x"}, ToolContext(tmp_path))
    assert result.error_code == "extension_secret_unavailable"
    assert runtime.calls == []
    assert registry.invocation_events()[0]["status"] == "error"
    executor.close()


def test_structured_runtime_error_is_redacted(tmp_path: Path) -> None:
    host_value = "runtime-host-value"

    def outcome(name, arguments, context):
        del name, arguments
        raise ConnectorInvocationError(
            f"remote denied value {context.auth_value}",
            code="remote_denied",
            retriable=False,
        )

    runtime = Runtime(outcome)
    registry, executor, tool = configured(
        tmp_path,
        runtime,
        MappingProjectSecretResolver({"secret://project/search": host_value}),
    )
    result = safe_execute(tool, {"query": "x"}, ToolContext(tmp_path))
    assert result.error_code == "remote_denied"
    assert host_value not in result.output
    assert "<REDACTED>" in result.output
    assert result.metadata["retriable"] is False
    assert registry.invocation_events()[0]["status"] == "error"
    executor.close()


def test_unsupported_schema_fails_before_registry_mutation(tmp_path: Path) -> None:
    ProjectManifestStore(tmp_path).initialize("Schema Failure Test")
    registry = ProjectExtensionRegistry(tmp_path)
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="connector.search",
            kind="connector",
            version="1.0.0",
            entrypoint="mcp:search",
            enabled=True,
            trust_source="verified",
            permissions=ExtensionPermissions(tools=("search",)),
        )
    )
    runtime = Runtime(lambda *_: ConnectorCallResult(True, "unused"))
    runtime.discover_tools = lambda: [
        {"name": "search", "input_schema": {"type": "object", "oneOf": []}}
    ]
    activator = ProjectExtensionActivator(
        registry,
        permission_ceiling=ExtensionPermissions(tools=("search",)),
        connector_factories={"search": lambda *_: runtime},
    )
    tools = ToolRegistry()
    with pytest.raises(Exception, match="unsupported JSON Schema keyword"):
        ProjectExtensionExecutor(activator).register_tools(tools)
    assert tools.names == ()
    assert runtime.closed
