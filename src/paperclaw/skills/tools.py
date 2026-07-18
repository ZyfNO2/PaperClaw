"""Agent-facing Skill discovery and bounded loading tools."""

from __future__ import annotations

import json
from typing import Any, Mapping

from paperclaw.tools.base import ToolContext, ToolResult, ToolValidationError, require_string, truncate

from .runtime import SkillRegistry


class SkillListTool:
    name = "skill_list"
    description = "List discoverable local, workspace and explicitly registered remote Skills."

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def validate(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ToolValidationError("skill_list accepts no arguments")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return _result(
            {"skills": [metadata.to_dict() for metadata in self.registry.list()]},
            context,
        )


class SkillTool:
    name = "skill_load"
    description = (
        "Load one Skill as a bounded instruction artifact. Arguments: name and "
        "optional parameters object. Loading a Skill does not execute tools or "
        "change permissions."
    )

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "name")
        parameters = arguments.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ToolValidationError("parameters must be an object")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        definition = self.registry.render(
            require_string(arguments, "name"),
            arguments.get("parameters", {}),
        )
        return _result(
            {
                "skill": definition.to_dict(include_instructions=True),
                "permission_effect": "none",
                "recursive_execution": False,
            },
            context,
        )


def _result(payload: dict[str, Any], context: ToolContext) -> ToolResult:
    rendered, was_truncated = truncate(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        context.output_limit,
    )
    return ToolResult(True, rendered, metadata={"result_truncated": was_truncated})


__all__ = ["SkillListTool", "SkillTool"]
