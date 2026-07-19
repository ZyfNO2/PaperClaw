from __future__ import annotations

import os
from pathlib import Path

import pytest

from paperclaw.eval.aggregate import MeteredChatModel, UsageCollector
from paperclaw.message_bus import SQLiteMessageBusStore
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.multiagent.bus_runtime import (
    BusDrivenTeamRuntime,
    SQLiteChoreographyStateStore,
    TeamRunRequest,
)
from paperclaw.multiagent.contracts import AgentTask, TeamBudget
from paperclaw.multiagent.coordinator import Coordinator

pytestmark = pytest.mark.real_llm


@pytest.mark.skipif(
    not os.environ.get("PAPERCLAW_API_KEY"),
    reason="PAPERCLAW_API_KEY is required for live v0.31 acceptance",
)
def test_live_provider_completes_bus_driven_team_run(tmp_path: Path):
    bus = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    state = SQLiteChoreographyStateStore(tmp_path / "state.sqlite3")

    def factory(budget, event_handler, usage):
        return Coordinator(
            lambda _agent_id: MeteredChatModel(
                OpenAICompatibleModel.from_env(),
                usage,
                provider=os.environ.get("PAPERCLAW_PROVIDER"),
                model=os.environ.get("PAPERCLAW_MODEL"),
            ),
            tmp_path,
            budget=budget,
            enable_verification_gate=False,
            event_handler=event_handler,
        )

    runtime = BusDrivenTeamRuntime(bus, state, factory, max_attempts=1)
    request = TeamRunRequest(
        request_id="live-team-acceptance",
        user_goal="Return a bounded completion for a no-tool research planning check.",
        tasks=(
            AgentTask(
                task_id="plan-check",
                title="plan check",
                objective="State that the bounded check is complete without calling a tool.",
                acceptance_criteria=["returns a structured done action"],
                allowed_paths=["."],
                allowed_tools=[],
                max_steps=3,
            ),
        ),
        budget=TeamBudget(
            max_agents=1,
            max_total_steps=3,
            max_total_model_calls=3,
            max_wall_time_seconds=90,
            max_fix_rounds=0,
        ),
    )
    outcome = runtime.execute(request, max_cycles=2)
    assert outcome.terminal is True
    assert outcome.dead_lettered is False
    assert outcome.result is not None
    assert outcome.metrics["model_calls"] >= 1
