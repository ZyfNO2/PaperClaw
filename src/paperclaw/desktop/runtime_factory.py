"""Production composition boundary for one desktop QueryEngine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from paperclaw.harness import ContextOrchestratedAgentRuntimeExecutor, QueryEngine
from paperclaw.memory import build_memory_runtime
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.models.reliability import RetryPolicy
from paperclaw.multiagent.tool import SubagentTaskTool
from paperclaw.tui.bridge import TUIEventBridge

from .contracts import DesktopRunRequest

DesktopEventHandler = Callable[[str, dict], None]


class DesktopRuntimeFactory:
    """Build the runtime from explicit run-scoped desktop values.

    Production defaults enable frozen project/user memory and Context orchestration.
    Supplying a custom executor keeps the legacy injectable call shape for tests.
    """

    def __init__(
        self,
        *,
        model_factory: Callable[..., Any] = OpenAICompatibleModel,
        executor_factory: Callable[..., Any] | None = None,
        engine_factory: Callable[..., Any] = QueryEngine,
        conversation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._model_factory = model_factory
        self._executor_factory = (
            executor_factory or ContextOrchestratedAgentRuntimeExecutor
        )
        self._context_enabled = executor_factory is None
        self._engine_factory = engine_factory
        self._conversation_id_factory = conversation_id_factory or (
            lambda: f"desktop-{uuid4().hex[:12]}"
        )

    def _create_model(self, request: DesktopRunRequest) -> Any:
        """Create one provider adapter per parent or subagent execution context."""

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
        if self._context_enabled:
            components = build_memory_runtime(request.workspace)
            components.tool_registry.register(
                SubagentTaskTool(
                    lambda _agent_id: self._create_model(request),
                    enable_verification_gate=request.enable_verification_gate,
                )
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
            conversation_id=self._conversation_id_factory(),
            event_handler=bridge.handle_query_event,
        )
