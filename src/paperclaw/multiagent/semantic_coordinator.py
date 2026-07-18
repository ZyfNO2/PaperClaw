"""Coordinator composition that injects a separately constructed semantic judge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from paperclaw.models.base import ChatModel

from .contracts import AgentTask, TeamBudget
from .coordinator import Coordinator
from .worker import Worker


class SemanticCoordinator(Coordinator):
    """Coordinator variant with a distinct model factory for semantic acceptance.

    The base Coordinator remains unchanged for compatibility.  This composition
    class only changes Worker construction and conservative model-call reservation.
    """

    _SEMANTIC_JUDGE_RESERVE = 2

    def __init__(
        self,
        model_factory: Callable[[str], ChatModel],
        workspace: Path | str,
        budget: TeamBudget | None = None,
        enable_verification_gate: bool = True,
        event_handler: Callable[[str, dict[str, Any]], None] | None = None,
        judge_model_factory: Callable[[str], ChatModel] | None = None,
    ) -> None:
        super().__init__(
            model_factory,
            workspace,
            budget=budget,
            enable_verification_gate=enable_verification_gate,
            event_handler=event_handler,
        )
        self._judge_model_factory = judge_model_factory

    def _make_worker(self, agent_id: str) -> Worker:
        judge_model = (
            self._judge_model_factory(f"judge-{agent_id}")
            if self._judge_model_factory is not None
            else None
        )
        return Worker(
            agent_id=agent_id,
            model=self._model_factory(agent_id),
            judge_model=judge_model,
            guard=self._guard,
            lease_manager=self._lease_manager,
            team_state=self._team_state,
            enable_verification_gate=self.enable_verification_gate,
        )

    def _model_call_upper_bound(self, task: AgentTask) -> int:
        bound = super()._model_call_upper_bound(task)
        if self._judge_model_factory is not None:
            bound += self._SEMANTIC_JUDGE_RESERVE
        return bound


__all__ = ["SemanticCoordinator"]
