from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from paperclaw.projects.extension_cli import main as extension_main
from paperclaw.projects.extension_execution import (
    ConnectorCallResult,
    ProjectExtensionExecutor,
    project_extension_tool_name,
)
from paperclaw.projects.extension_runtime import ProjectExtensionActivator
from paperclaw.projects.extensions import (
    ExtensionPermissions,
    ProjectExtensionDescriptor,
    ProjectExtensionRegistry,
)
from paperclaw.projects.manifest import ProjectManifestStore
from paperclaw.tools.base import ToolContext, ToolControlFlow, ToolResult, safe_execute
from paperclaw.tools.registry import ToolRegistry


INPUT_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "minLength": 1}},
    "required": ["query"],
    "additionalProperties": False,
}


class Runtime:
    def __init__(self, outcome=None, *, delay: float = 0.0) -> None:
        self.outcome = outcome
        self.delay = delay
        self.closed = False
        self.calls = []

    def discover_tools(self):
        return [
            {
                "name": "search",
                "description": "Search project evidence",
                "input_schema": INPUT_SCHEMA,
            }
        ]

    def call_tool(self, name, arguments, context):
        self.calls.append((name, arguments, context))
        if self.delay:
            time.sleep(self.delay)
        if callable(self.outcome):
            return self.outcome(name, arguments, context)
        if self.outcome is not None:
            return self.outcome
        return ConnectorCallResult(True, {"matches": [arguments["query"]]})

    def close(self) -> None:
        self.closed = True


class DiscoveryOnlyRuntime:
    def __init__(self) -> None:
        self.closed = False

    def discover_tools(self):
        return [{"name": "search", "input_schema": INPUT_SCHEMA}]

    def close(self) -> None:
        self.closed = True


class MutableStopToken:
    def __init__(self) -> None:
        self.cancelled = False
        self._reason = None

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled

    @property
    def reason(self) -> str | None:
        return self._reason

    def cancel(self, reason: str) -> None:
        self._reason = reason
        self.cancelled = True


class ExistingTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "existing"

    def validate(self, arguments):
        del arguments

    def execute(self, arguments, context):
        del arguments, context
        return ToolResult(True, "existing")


def workspace(tmp_path: Path) -> Path:
    ProjectManifestStore(tmp_path).initialize("Extension Execution Test")
    return tmp_path


def configured(
    tmp_path: Path,
    runtime,
    *,
    timeout_seconds: float = 1.0,
):
    root = workspace(tmp_path)
    registry = ProjectExtensionRegistry(root)
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="connector.search",
            kind="connector",
            version="1.0.0",
            entrypoint="mcp:search",
            enabled=True,
            trust_source="verified",
            permissions=ExtensionPermissions(
                tools=("search",),
                network_hosts=("search.example.com",),
            ),
        )
    )
    activator = ProjectExtensionActivator(
        registry,
        permission_ceiling=ExtensionPermissions(
            tools=("search",),
            network_hosts=("search.example.com",),
        ),
        connector_factories={"search": lambda *_: runtime},
    )
    executor = ProjectExtensionExecutor(
        activator,
        timeout_seconds=timeout_seconds,
    )
    tools = ToolRegistry()
    registration = executor.register_tools(tools)
    tool = tools.get(registration.registered_tools[0])
    return root, registry, executor, runtime, tools, tool


def test_execution_returns_bounded_result_and_audits(tmp_path: Path) -> None:
    root, registry, executor, runtime, _, tool = configured(tmp_path, Runtime())
    result = safe_execute(tool, {"query": "evidence"}, ToolContext(root))
    assert result.ok
    assert json.loads(result.output) == {"matches": ["evidence"]}
    assert result.metadata["extension_id"] == "connector.search"
    assert result.metadata["remote_tool"] == "search"
    event = registry.invocation_events()[0]
    assert event["status"] == "success"
    assert event["error_code"] is None
    assert event["argument_bytes"] > 0
    assert event["result_bytes"] > 0
    executor.close()
    assert runtime.closed


def test_schema_validation_happens_before_runtime_call(tmp_path: Path) -> None:
    _, registry, executor, runtime, _, tool = configured(tmp_path, Runtime())
    result = safe_execute(tool, {"query": "", "extra": True}, ToolContext(tmp_path))
    assert not result.ok
    assert result.error_code == "validation_error"
    assert runtime.calls == []
    assert registry.invocation_events() == ()
    executor.close()


def test_disable_and_descriptor_change_are_rechecked_at_call_time(tmp_path: Path) -> None:
    root, registry, executor, runtime, _, tool = configured(tmp_path, Runtime())
    registry.set_enabled("connector.search", False)
    disabled = safe_execute(tool, {"query": "x"}, ToolContext(root))
    assert disabled.error_code == "extension_disabled"
    assert runtime.calls == []
    assert registry.invocation_events()[0]["status"] == "denied"

    registry.register(
        ProjectExtensionDescriptor(
            extension_id="connector.search",
            kind="connector",
            version="2.0.0",
            entrypoint="mcp:search",
            enabled=True,
            trust_source="verified",
            permissions=ExtensionPermissions(
                tools=("search",),
                network_hosts=("search.example.com",),
            ),
        ),
        replace_existing=True,
    )
    changed = safe_execute(tool, {"query": "x"}, ToolContext(root))
    assert changed.error_code == "extension_changed"
    assert runtime.calls == []
    executor.close()


def test_permission_ceiling_is_rechecked_at_call_time(tmp_path: Path) -> None:
    root, registry, executor, runtime, _, tool = configured(tmp_path, Runtime())
    executor.activator.permission_ceiling = ExtensionPermissions()
    result = safe_execute(tool, {"query": "x"}, ToolContext(root))
    assert result.error_code == "extension_permission_denied"
    assert runtime.calls == []
    assert registry.invocation_events()[0]["status"] == "denied"
    executor.close()


def test_timeout_closes_runtime_and_records_timeout(tmp_path: Path) -> None:
    root, registry, executor, runtime, _, tool = configured(
        tmp_path,
        Runtime(delay=0.2),
        timeout_seconds=0.03,
    )
    result = safe_execute(tool, {"query": "slow"}, ToolContext(root))
    assert result.error_code == "extension_timeout"
    assert runtime.closed
    event = registry.invocation_events()[0]
    assert event["status"] == "timeout"
    assert event["error_code"] == "extension_timeout"
    executor.close()


def test_cancellation_crosses_safe_execute_and_is_audited(tmp_path: Path) -> None:
    root, registry, executor, runtime, _, tool = configured(
        tmp_path,
        Runtime(delay=0.2),
        timeout_seconds=1.0,
    )
    token = MutableStopToken()
    threading.Timer(0.03, lambda: token.cancel("user_cancelled")).start()
    with pytest.raises(ToolControlFlow, match="user_cancelled"):
        safe_execute(
            tool,
            {"query": "cancel"},
            ToolContext(root, stop_token=token),
        )
    assert runtime.closed
    event = registry.invocation_events()[0]
    assert event["status"] == "cancelled"
    assert event["error_code"] == "extension_cancelled"
    executor.close()


def test_registration_rejects_non_executable_runtime_atomically(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    registry = ProjectExtensionRegistry(root)
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
    runtime = DiscoveryOnlyRuntime()
    activator = ProjectExtensionActivator(
        registry,
        permission_ceiling=ExtensionPermissions(tools=("search",)),
        connector_factories={"search": lambda *_: runtime},
    )
    tools = ToolRegistry()
    with pytest.raises(TypeError, match="call_tool"):
        ProjectExtensionExecutor(activator).register_tools(tools)
    assert tools.names == ()
    assert runtime.closed


def test_registry_collision_is_detected_before_registration(tmp_path: Path) -> None:
    runtime = Runtime()
    root = workspace(tmp_path)
    registry = ProjectExtensionRegistry(root)
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
    activator = ProjectExtensionActivator(
        registry,
        permission_ceiling=ExtensionPermissions(tools=("search",)),
        connector_factories={"search": lambda *_: runtime},
    )
    name = project_extension_tool_name("connector.search", "search")
    tools = ToolRegistry([ExistingTool(name)])
    with pytest.raises(ValueError, match="name collision"):
        ProjectExtensionExecutor(activator).register_tools(tools)
    assert tools.names == (name,)
    assert runtime.closed


def test_cli_audit_includes_content_free_invocations(tmp_path: Path, capsys) -> None:
    root, _, executor, _, _, tool = configured(tmp_path, Runtime())
    assert safe_execute(tool, {"query": "cli"}, ToolContext(root)).ok
    assert extension_main(["--workspace", str(root), "audit"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["events"][0]["action"] == "register"
    invocation = payload["invocations"][0]
    assert invocation["tool_name"] == "search"
    assert "query" not in invocation
    executor.close()
