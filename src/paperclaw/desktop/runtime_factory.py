"""Production composition boundary for one desktop QueryEngine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.models.reliability import RetryPolicy
from paperclaw.tui.bridge import TUIEventBridge

from .contracts import DesktopRunRequest

DesktopEventHandler = Callable[[str, dict], None]


class DesktopRuntimeFactory:
    """Build the existing runtime from explicit run-scoped desktop values.

    Dependencies are injectable for offline tests. No environment variable is
    mutated and ``OpenAICompatibleModel.from_env`` remains untouched.
    """

    def __init__(
        self,
        *,
        model_factory: Callable[..., Any] = OpenAICompatibleModel,
        executor_factory: Callable[..., Any] = AgentRuntimeExecutor,
        engine_factory: Callable[..., Any] = QueryEngine,
        conversation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._model_factory = model_factory
        self._executor_factory = executor_factory
        self._engine_factory = engine_factory
        self._conversation_id_factory = conversation_id_factory or (
            lambda: f"desktop-{uuid4().hex[:12]}"
        )

    def create(
        self,
        request: DesktopRunRequest,
        event_handler: DesktopEventHandler,
    ) -> Any:
        bridge = TUIEventBridge(event_handler)
        model = self._model_factory(
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            timeout=120,
            provider=request.provider,
            retry_policy=RetryPolicy(max_attempts=3),
        )
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
