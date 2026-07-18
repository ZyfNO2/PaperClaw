"""Production QueryEngine composition for the optional service layer."""

from __future__ import annotations

from collections.abc import Callable
<<<<<<< HEAD
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
=======
from dataclasses import replace
import os
from typing import Any
from uuid import uuid4

>>>>>>> 77ef8ea
from paperclaw.agent.flow import default_registry
from paperclaw.harness import (
    AgentRuntimeExecutor,
    ContextOrchestratedAgentRuntimeExecutor,
    QueryEngine,
)
<<<<<<< HEAD
from paperclaw.memory import MemoryTool, build_memory_runtime
>>>>>>> 70e7334
=======
from paperclaw.memory import (
    MemoryRuntimeSettings,
    MemoryTool,
    build_memory_runtime,
)
>>>>>>> 77ef8ea
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.policy import (
    DefaultToolAuthorizationPolicy,
    ToolAuthorizationPolicy,
    authorize_registry,
)
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
=======
>>>>>>> 77ef8ea
from paperclaw.tui.bridge import TUIEventBridge

from .contracts import ServiceRunRequest


class ServiceRuntimeFactory:
<<<<<<< HEAD
<<<<<<< HEAD
    """Build one environment-backed QueryEngine per service submission."""
=======
    """Build one environment-backed QueryEngine per service submission.

    The production default uses Context orchestration, frozen project/user memory,
    and deterministic in-run compaction. Supplying ``executor_factory`` preserves
    the legacy injectable boundary used by offline tests and custom runtimes.
    """
>>>>>>> 70e7334
=======
    """Build one environment-backed QueryEngine per service submission.

    Context orchestration and deterministic in-run compaction are enabled by
    default. Personal ``USER.md``/``MEMORY.md`` injection and writes are disabled
    for the unauthenticated HTTP service unless trusted deployment configuration
    explicitly enables them. Supplying ``executor_factory`` preserves the legacy
    injectable boundary used by offline tests and custom runtimes.
    """
>>>>>>> 77ef8ea

    def __init__(
        self,
        *,
        model_factory: Callable[[], Any] = OpenAICompatibleModel.from_env,
<<<<<<< HEAD
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
=======
        executor_factory: Callable[..., Any] | None = None,
        engine_factory: Callable[..., Any] = QueryEngine,
        tool_policy: ToolAuthorizationPolicy | None = None,
        enable_personal_memory: bool | None = None,
>>>>>>> 77ef8ea
    ) -> None:
        self._model_factory = model_factory
        self._executor_factory = (
            executor_factory or ContextOrchestratedAgentRuntimeExecutor
        )
        self._context_enabled = executor_factory is None
        self._engine_factory = engine_factory
        self._tool_policy = tool_policy or DefaultToolAuthorizationPolicy()
<<<<<<< HEAD
>>>>>>> 70e7334
=======
        self._enable_personal_memory = (
            _env_bool("PAPERCLAW_SERVICE_PERSONAL_MEMORY_ENABLED", False)
            if enable_personal_memory is None
            else bool(enable_personal_memory)
        )
>>>>>>> 77ef8ea

    def create(
        self,
        request: ServiceRunRequest,
        event_handler: Callable[[str, dict], None],
    ) -> QueryEngine:
        bridge = TUIEventBridge(event_handler)
        model = self._model_factory()
<<<<<<< HEAD
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
=======
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
>>>>>>> 77ef8ea
            registry = authorize_registry(
                default_registry(),
                workspace=request.workspace,
                policy=self._tool_policy,
            )
            if (
<<<<<<< HEAD
                components.settings.memory_enabled
                and components.settings.memory_tool_enabled
            ):
                # The bounded local memory tool has its own schema, privacy and
                # capacity checks. It is intentionally composed after generic
                # workspace/external-tool authorization because it writes only to
                # the trusted per-user PaperClaw memory directory.
=======
                self._enable_personal_memory
                and components.settings.memory_enabled
                and components.settings.memory_tool_enabled
            ):
                # Explicit deployment opt-in is required because the current API
                # has no authenticated tenant ownership boundary.
>>>>>>> 77ef8ea
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
<<<<<<< HEAD
>>>>>>> 70e7334
=======
>>>>>>> 77ef8ea
        conversation_id = request.conversation_id or f"api-{uuid4().hex[:12]}"
        return self._engine_factory(
            executor,
            conversation_id=conversation_id,
            event_handler=bridge.handle_query_event,
        )
<<<<<<< HEAD
=======


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
>>>>>>> 77ef8ea
