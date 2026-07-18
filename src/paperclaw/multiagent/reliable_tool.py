"""v0.22 composition for subagent delegation with semantic acceptance enabled."""

from __future__ import annotations

from typing import Any, Callable

from paperclaw.models.base import ChatModel

from .coordinator import Coordinator
from .semantic_coordinator import SemanticCoordinator
from .tool import SubagentTaskTool


class ReliableSubagentTaskTool(SubagentTaskTool):
    """Subagent tool that keeps execution and semantic judge factories separate."""

    def __init__(
        self,
        model_factory: Callable[[str], ChatModel],
        *,
        judge_model_factory: Callable[[str], ChatModel],
        enable_verification_gate: bool = True,
        event_handler: Callable[[str, dict[str, Any]], None] | None = None,
        coordinator_factory: Callable[..., Coordinator] | None = None,
    ) -> None:
        if coordinator_factory is None:

            def coordinator_factory_with_judge(*args: Any, **kwargs: Any) -> Coordinator:
                return SemanticCoordinator(
                    *args,
                    **kwargs,
                    judge_model_factory=judge_model_factory,
                )

            selected_factory = coordinator_factory_with_judge
        else:
            selected_factory = coordinator_factory
        super().__init__(
            model_factory,
            coordinator_factory=selected_factory,
            enable_verification_gate=enable_verification_gate,
            event_handler=event_handler,
        )
        self._judge_model_factory = judge_model_factory


__all__ = ["ReliableSubagentTaskTool"]
