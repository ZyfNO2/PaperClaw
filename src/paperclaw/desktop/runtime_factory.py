"""Production composition boundary for one desktop QueryEngine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from paperclaw.harness import ContextOrchestratedAgentRuntimeExecutor, QueryEngine
from paperclaw.lsp.bootstrap import get_lsp_manager
from paperclaw.lsp.tools import register_lsp_tools
from paperclaw.memory import build_memory_runtime
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.models.reliability import RetryPolicy
from paperclaw.multiagent.tool import SubagentTaskTool
from paperclaw.planning.bootstrap import compose_plan_and_skills
from paperclaw.tasks.bootstrap import get_or_create_task_runtime
from paperclaw.tasks.tools import register_task_tools
from paperclaw.tui.bridge import TUIEventBridge

from .contracts import DesktopRunRequest

DesktopEventHandler = Callable[[str, dict], None]


class DesktopRuntimeFactory:
    """Build one scoped parent runtime and reuse process-scoped services."""

    def __init__(
        self,
        *,
        model_factory: Callable[..., Any] = OpenAICompatibleModel,
        executor_factory: Callable[..., Any] | None = None,
        engine_factory: Callable[..., Any] = QueryEngine,
        conversation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._model_factory = model_factory
        self._executor_factory = executor_factory or ContextOrchestratedAgentRuntimeExecutor
        self._context_enabled = executor_factory is None
        self._engine_factory = engine_factory
        self._conversation_id_factory = conversation_id_factory or (
            lambda: f"desktop-{uuid4().hex[:12]}"
        )

    def _create_model(self, request: DesktopRunRequest) -> Any:
        return self._model_factory(
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            timeout=120,
            provider=request.provider,
            retry_policy=RetryPolicy(max_attempts=3),
        )

    def create(
        self,
        request: DesktopRunRequest,
        event_handler: DesktopEventHandler,
    ) -> Any:
        bridge = TUIEventBridge(event_handler)
        model = self._create_model(request)
        conversation_id = self._conversation_id_factory()
        if self._context_enabled:
            components = build_memory_runtime(request.workspace)
            model_factory = lambda _agent_id: self._create_model(request)
            components.tool_registry.register(
                SubagentTaskTool(
                    model_factory,
                    enable_verification_gate=request.enable_verification_gate,
                )
            )
            task_runtime = get_or_create_task_runtime(
                model_factory,
                cache_key=f"desktop:{request.provider}:{request.base_url}:{request.model}",
                worker_id="desktop-task-worker",
            )
            register_task_tools(
                components.tool_registry,
                task_runtime.store,
                task_runtime.supervisor,
            )
            components, _plan_controller, _skills = compose_plan_and_skills(
                components,
                workspace=request.workspace,
                scope_id=conversation_id,
            )
            register_lsp_tools(
                components.tool_registry,
                get_lsp_manager(request.workspace),
            )
            executor = self._executor_factory(
                model,
                request.workspace,
                registry=components.tool_registry,
                enable_verification_gate=request.enable_verification_gate,
                legacy_event_handler=bridge.handle_legacy_event,
                context_policy=components.context_policy,
                context_source_registry=components.source_registry,
            )
        else:
            executor = self._executor_factory(
                model,
                request.workspace,
                enable_verification_gate=request.enable_verification_gate,
                legacy_event_handler=bridge.handle_legacy_event,
            )
        return self._engine_factory(
            executor,
            conversation_id=conversation_id,
            event_handler=bridge.handle_query_event,
        )
