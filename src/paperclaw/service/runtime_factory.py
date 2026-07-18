"""Production QueryEngine composition for the optional service layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import os
from typing import Any
from uuid import uuid4

from paperclaw.agent.flow import default_registry
from paperclaw.harness import ContextOrchestratedAgentRuntimeExecutor, QueryEngine
from paperclaw.memory import MemoryRuntimeSettings, MemoryTool, build_memory_runtime
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.planning.bootstrap import default_plan_database
from paperclaw.planning.runtime import SQLitePlanStore
from paperclaw.planning.tools import PlanController, compose_plan_registry
from paperclaw.policy import (
    DefaultToolAuthorizationPolicy,
    ToolAuthorizationPolicy,
    authorize_registry,
)
from paperclaw.skills.runtime import SkillRegistry
from paperclaw.skills.tools import SkillListTool, SkillTool
from paperclaw.tasks.bootstrap import TaskRuntimeComponents
from paperclaw.tasks.tools import register_task_tools
from paperclaw.tui.bridge import TUIEventBridge

from .contracts import ServiceRunRequest


class ServiceRuntimeFactory:
    """Build one environment-backed QueryEngine per service submission."""

    def __init__(
        self,
        *,
        model_factory: Callable[[], Any] = OpenAICompatibleModel.from_env,
        executor_factory: Callable[..., Any] | None = None,
        engine_factory: Callable[..., Any] = QueryEngine,
        tool_policy: ToolAuthorizationPolicy | None = None,
        enable_personal_memory: bool | None = None,
        task_runtime: TaskRuntimeComponents | None = None,
    ) -> None:
        self._model_factory = model_factory
        self._executor_factory = executor_factory or ContextOrchestratedAgentRuntimeExecutor
        self._context_enabled = executor_factory is None
        self._engine_factory = engine_factory
        self._tool_policy = tool_policy or DefaultToolAuthorizationPolicy()
        self._enable_personal_memory = (
            _env_bool("PAPERCLAW_SERVICE_PERSONAL_MEMORY_ENABLED", False)
            if enable_personal_memory is None
            else bool(enable_personal_memory)
        )
        self._task_runtime = task_runtime

    def create(
        self,
        request: ServiceRunRequest,
        event_handler: Callable[[str, dict], None],
    ) -> QueryEngine:
        bridge = TUIEventBridge(event_handler)
        model = self._model_factory()
        conversation_id = request.conversation_id or f"api-{uuid4().hex[:12]}"
        registry = authorize_registry(
            default_registry(),
            workspace=request.workspace,
            policy=self._tool_policy,
        )
        if self._task_runtime is not None:
            register_task_tools(
                registry,
                self._task_runtime.store,
                self._task_runtime.supervisor,
            )

        plan_controller = PlanController(
            SQLitePlanStore(default_plan_database()),
            conversation_id,
        )
        registry = compose_plan_registry(registry, plan_controller)
        skills = SkillRegistry(workspace=request.workspace)
        registry.register(SkillListTool(skills))
        registry.register(SkillTool(skills))

        if self._context_enabled:
            settings = MemoryRuntimeSettings.from_env()
            if not self._enable_personal_memory:
                settings = replace(
                    settings,
                    memory_enabled=False,
                    user_profile_enabled=False,
                    memory_tool_enabled=False,
                )
            components = build_memory_runtime(request.workspace, settings=settings)
            if (
                self._enable_personal_memory
                and components.settings.memory_enabled
                and components.settings.memory_tool_enabled
            ):
                registry.register(MemoryTool(components.store))
            executor = self._executor_factory(
                model,
                request.workspace,
                registry=registry,
                enable_verification_gate=request.enable_verification_gate,
                legacy_event_handler=bridge.handle_legacy_event,
                context_policy=components.context_policy,
                context_source_registry=components.source_registry,
            )
        else:
            executor = self._executor_factory(
                model,
                request.workspace,
                registry=registry,
                enable_verification_gate=request.enable_verification_gate,
                legacy_event_handler=bridge.handle_legacy_event,
            )
        return self._engine_factory(
            executor,
            conversation_id=conversation_id,
            event_handler=bridge.handle_query_event,
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")
