"""Production QueryEngine composition for the optional service layer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.tui.bridge import TUIEventBridge

from .contracts import ServiceRunRequest


class ServiceRuntimeFactory:
    """Build one environment-backed QueryEngine per service submission."""

    def __init__(
        self,
        *,
        model_factory: Callable[[], Any] = OpenAICompatibleModel.from_env,
        executor_factory: Callable[..., Any] = AgentRuntimeExecutor,
        engine_factory: Callable[..., Any] = QueryEngine,
    ) -> None:
        self._model_factory = model_factory
        self._executor_factory = executor_factory
        self._engine_factory = engine_factory

    def create(
        self,
        request: ServiceRunRequest,
        event_handler: Callable[[str, dict], None],
    ) -> QueryEngine:
        bridge = TUIEventBridge(event_handler)
        model = self._model_factory()
        executor = self._executor_factory(
            model,
            request.workspace,
            enable_verification_gate=request.enable_verification_gate,
            legacy_event_handler=bridge.handle_legacy_event,
        )
        conversation_id = request.conversation_id or f"api-{uuid4().hex[:12]}"
        return self._engine_factory(
            executor,
            conversation_id=conversation_id,
            event_handler=bridge.handle_query_event,
        )
