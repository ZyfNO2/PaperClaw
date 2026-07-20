from __future__ import annotations

import os
from pathlib import Path

import pytest

from paperclaw.eval.aggregate import MeteredChatModel, PricingTable, aggregate_runs
from paperclaw.message_bus import SQLiteMessageBusStore
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.multiagent.bus_runtime import (
    BusDrivenTeamRuntime,
    SQLiteChoreographyStateStore,
    TeamRunRequest,
)
from paperclaw.multiagent.contracts import AgentTask, TeamBudget
from paperclaw.multiagent.observed_runtime import (
    ObservedCoordinator,
    SQLiteTeamTraceBridge,
    TraceUsageCollector,
    team_run_id,
)
from paperclaw.trace import SQLiteTraceReader

pytestmark = pytest.mark.real_llm


@pytest.mark.skipif(
    not os.environ.get("PAPERCLAW_API_KEY"),
    reason="PAPERCLAW_API_KEY is required for live v0.32 acceptance",
)
def test_live_provider_team_run_is_queryable_by_aggregate_eval(tmp_path: Path):
    request_id = "live-v032-trace-eval"
    raw_bus = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    trace_database = tmp_path / "traces.sqlite3"
    bridge = SQLiteTeamTraceBridge(raw_bus, trace_database)
    state = SQLiteChoreographyStateStore(tmp_path / "state.sqlite3")
    pricing = PricingTable()

    def factory(budget, event_handler, usage):
        return ObservedCoordinator(
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

    runtime = BusDrivenTeamRuntime(
        bridge,
        state,
        factory,
        max_attempts=1,
        usage_factory=lambda: TraceUsageCollector(pricing, bridge, request_id),
    )
    request = TeamRunRequest(
        request_id=request_id,
        user_goal="Return a bounded structured completion for the v0.32 trace check.",
        tasks=(
            AgentTask(
                task_id="trace-check",
                title="trace check",
                objective="State that the bounded trace check is complete without a tool.",
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

    try:
        outcome = runtime.execute(request, max_cycles=2)
    finally:
        bridge.close()

    assert outcome.terminal is True
    assert outcome.dead_lettered is False
    assert outcome.result is not None

    reader = SQLiteTraceReader(trace_database)
    report = aggregate_runs(reader, [team_run_id(request_id)])
    assert report.success_count == 1
    assert report.total_model_calls >= 1
    assert report.total_tokens >= 0
    assert report.unpriced_model_calls >= 1
    assert report.runs[0].terminal_event == "run.completed"
