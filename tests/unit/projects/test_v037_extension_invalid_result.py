from __future__ import annotations

from pathlib import Path

from paperclaw.projects.extension_execution import ProjectExtensionExecutor
from paperclaw.projects.extension_runtime import ProjectExtensionActivator
from paperclaw.projects.extensions import (
    ExtensionPermissions,
    ProjectExtensionDescriptor,
    ProjectExtensionRegistry,
)
from paperclaw.projects.manifest import ProjectManifestStore
from paperclaw.tools.base import ToolContext, safe_execute
from paperclaw.tools.registry import ToolRegistry


class InvalidResultRuntime:
    def __init__(self) -> None:
        self.closed = False

    def discover_tools(self):
        return [
            {
                "name": "search",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
        ]

    def call_tool(self, name, arguments, context):
        del name, arguments, context
        return {"not": "a ConnectorCallResult"}

    def close(self) -> None:
        self.closed = True


def test_invalid_runtime_result_fails_closed_and_is_audited(tmp_path: Path) -> None:
    ProjectManifestStore(tmp_path).initialize("Invalid Result Test")
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
    runtime = InvalidResultRuntime()
    activator = ProjectExtensionActivator(
        registry,
        permission_ceiling=ExtensionPermissions(tools=("search",)),
        connector_factories={"search": lambda *_: runtime},
    )
    executor = ProjectExtensionExecutor(activator)
    tools = ToolRegistry()
    registration = executor.register_tools(tools)
    result = safe_execute(
        tools.get(registration.registered_tools[0]),
        {},
        ToolContext(tmp_path),
    )
    assert result.error_code == "extension_invalid_result"
    assert runtime.closed
    event = registry.invocation_events()[0]
    assert event["status"] == "error"
    assert event["error_code"] == "extension_invalid_result"
    executor.close()
