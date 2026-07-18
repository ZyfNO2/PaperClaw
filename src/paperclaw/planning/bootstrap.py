"""Composition helpers for Plan Mode, AskUserQuestion and Skills."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from typing import Any

from paperclaw.memory.runtime import MemoryRuntimeComponents
from paperclaw.skills.runtime import SkillRegistry
from paperclaw.skills.tools import SkillListTool, SkillTool

from .runtime import SQLitePlanStore
from .tools import PlanController, compose_plan_registry

_CLI_MARKER = "_paperclaw_plan_skill_cli_extension"


def default_plan_database() -> Path:
    configured = os.getenv("PAPERCLAW_PLAN_DATABASE")
    path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".paperclaw" / "plans.sqlite3"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def compose_plan_and_skills(
    components: MemoryRuntimeComponents,
    *,
    workspace: str | Path,
    scope_id: str,
    database: str | Path | None = None,
) -> tuple[MemoryRuntimeComponents, PlanController, SkillRegistry]:
    store = SQLitePlanStore(database or default_plan_database())
    controller = PlanController(store, scope_id)
    registry = compose_plan_registry(components.tool_registry, controller)
    skills = SkillRegistry(workspace=workspace)
    registry.register(SkillListTool(skills))
    registry.register(SkillTool(skills))
    return replace(components, tool_registry=registry), controller, skills


def install_cli_plan_skill_extension(cli_module: Any) -> None:
    if getattr(cli_module, _CLI_MARKER, False):
        return
    original_build_memory_runtime = cli_module.build_memory_runtime

    def build_memory_runtime_with_plan_skills(workspace, *args: Any, **kwargs: Any):
        components = original_build_memory_runtime(workspace, *args, **kwargs)
        resolved = Path(workspace).expanduser().resolve()
        enhanced, _controller, _skills = compose_plan_and_skills(
            components,
            workspace=resolved,
            scope_id=f"cli:{resolved}",
        )
        return enhanced

    cli_module.build_memory_runtime = build_memory_runtime_with_plan_skills
    setattr(cli_module, _CLI_MARKER, True)


__all__ = [
    "compose_plan_and_skills",
    "default_plan_database",
    "install_cli_plan_skill_extension",
]
