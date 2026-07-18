"""Production QueryEngine composition for the optional service layer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

<<<<<<< HEAD
<<<<<<< HEAD
from paperclaw.harness import AgentRuntimeExecutor, QueryEngine
from paperclaw.models.adapters import OpenAICompatibleModel
=======
from paperclaw.agent.flow import default_registry
from paperclaw.harness import AgentRuntimeExecutor, QueryEngine
=======
from paperclaw.agent.flow import default_registry
from paperclaw.harness import (
    AgentRuntimeExecutor,
    ContextOrchestratedAgentRuntimeExecutor,
    QueryEngine,
)
from paperclaw.memory import MemoryTool, build_memory_runtime
>>>>>>> 70e7334
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.policy import (
    DefaultToolAuthorizationPolicy,
    ToolAuthorizationPolicy,
    authorize_registry,
)
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
from paperclaw.tui.bridge import TUIEventBridge

from .contracts import ServiceRunRequest


class ServiceRuntimeFactory:
<<<<<<< HEAD
    """Build one environment-backed QueryEngine per service submission."""
=======
    """Build one environment-backed QueryEngine per service submission.

    The production default uses Context orchestration, frozen project/user memory,
    and deterministic in-run compaction. Supplying ``executor_factory`` preserves
    the legacy injectable boundary used by offline tests and custom runtimes.
    """
>>>>>>> 70e7334

    def __init__(
        self,
        *,
        model_factory: Callable[[], Any] = OpenAICompatibleModel.from_env,
<<<<<<< HEAD
        executor_factory: Callable[..., Any] = AgentRuntimeExecutor,
        engine_factory: Callable[..., Any] = QueryEngine,
<<<<<<< HEAD
=======
        tool_policy: ToolAuthorizationPolicy | None = None,
>>>>>>> 18cf7be
    ) -> None:
        self._model_factory = model_factory
        self._executor_factory = executor_factory
        self._engine_factory = engine_factory
<<<<<<< HEAD
=======
        self._tool_policy = tool_policy or DefaultToolAuthorizationPolicy()
>>>>>>> 18cf7be
=======
        executor_factory: Callable[..., Any] | None = None,
        engine_factory: Callable[..., Any] = QueryEngine,
        tool_policy: ToolAuthorizationPolicy | None = None,
    ) -> None:
        self._model_factory = model_factory
        self._executor_factory = (
            executor_factory or ContextOrchestratedAgentRuntimeExecutor
        )
        self._context_enabled = executor_factory is None
        self._engine_factory = engine_factory
        self._tool_policy = tool_policy or DefaultToolAuthorizationPolicy()
>>>>>>> 70e7334

    def create(
        self,
        request: ServiceRunRequest,
        event_handler: Callable[[str, dict], None],
    ) -> QueryEngine:
        bridge = TUIEventBridge(event_handler)
        model = self._model_factory()
<<<<<<< HEAD
<<<<<<< HEAD
        executor = self._executor_factory(
            model,
            request.workspace,
=======
        registry = authorize_registry(
            default_registry(),
            workspace=request.workspace,
            policy=self._tool_policy,
        )
        executor = self._executor_factory(
            model,
            request.workspace,
            registry=registry,
>>>>>>> 18cf7be
            enable_verification_gate=request.enable_verification_gate,
            legacy_event_handler=bridge.handle_legacy_event,
        )
=======
        if self._context_enabled:
            components = build_memory_runtime(request.workspace)
            registry = authorize_registry(
                default_registry(),
                workspace=request.workspace,
                policy=self._tool_policy,
            )
            if (
                components.settings.memory_enabled
                and components.settings.memory_tool_enabled
            ):
                # The bounded local memory tool has its own schema, privacy and
                # capacity checks. It is intentionally composed after generic
                # workspace/external-tool authorization because it writes only to
                # the trusted per-user PaperClaw memory directory.
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
            registry = authorize_registry(
                default_registry(),
                workspace=request.workspace,
                policy=self._tool_policy,
            )
            executor = self._executor_factory(
                model,
                request.workspace,
                registry=registry,
                enable_verification_gate=request.enable_verification_gate,
                legacy_event_handler=bridge.handle_legacy_event,
            )
>>>>>>> 70e7334
        conversation_id = request.conversation_id or f"api-{uuid4().hex[:12]}"
        return self._engine_factory(
            executor,
            conversation_id=conversation_id,
            event_handler=bridge.handle_query_event,
        )
