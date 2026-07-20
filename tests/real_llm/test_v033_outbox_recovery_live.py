from __future__ import annotations

import os
from pathlib import Path

import pytest

from paperclaw.eval.aggregate import MeteredChatModel, PricingTable, aggregate_runs
from paperclaw.message_bus import SQLiteMessageBusStore
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.multiagent.bus_runtime import TeamRunRequest
from paperclaw.multiagent.contracts import AgentTask, TeamBudget
from paperclaw.multiagent.observed_runtime import (
    ObservedCoordinator,
    SQLiteTeamTraceBridge,
    TraceUsageCollector,
    team_run_id,
)
from paperclaw.multiagent.ordered_outbox import (
    SQLiteOrderedResilientChoreographyStore,
)
from paperclaw.multiagent.resilient_runtime import (
    InjectedCrash,
    ResilientBusDrivenTeamRuntime,
)
from paperclaw.trace import SQLiteTraceReader

pytestmark = pytest.mark.real_llm


class CrashAfterTerminalCommit:
    def __init__(self):
        self.fired = False

    def __call__(self, checkpoint, context):
        if checkpoint == "after_terminal_committed" and not self.fired:
            self.fired = True
            raise InjectedCrash(checkpoint)


@pytest.mark.skipif(
    not os.environ.get("PAPERCLAW_API_KEY"),
    reason="PAPERCLAW_API_KEY is required",
)
def test_live_provider_is_not_reexecuted_after_terminal_commit_crash(tmp_path: Path):
    request_id = "live-v033-outbox-recovery"
    bus_database = tmp_path / "bus.sqlite3"
    state_database = tmp_path / "state.sqlite3"
    trace_database = tmp_path / "traces.sqlite3"
    bridge = SQLiteTeamTraceBridge(
        SQLiteMessageBusStore(bus_database),
        trace_database,
    )
    state = SQLiteOrderedResilientChoreographyStore(state_database)
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

    request = TeamRunRequest(
        request_id=request_id,
        user_goal="Return one bounded structured completion for Outbox recovery.",
        tasks=(
            AgentTask(
                task_id="recovery-check",
                title="recovery check",
                objective=(
                    "State that the bounded recovery check is complete without a tool."
                ),
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
    runtime = ResilientBusDrivenTeamRuntime(
        bridge,
        state,
        factory,
        max_attempts=1,
        fault_injector=CrashAfterTerminalCommit(),
        usage_factory=lambda: TraceUsageCollector(pricing, bridge, request_id),
    )
    runtime.submit(request)
    with pytest.raises(InjectedCrash):
        runtime.run_once()
    bridge.close()

    restarted_bridge = SQLiteTeamTraceBridge(
        SQLiteMessageBusStore(bus_database),
        trace_database,
    )
    restarted = ResilientBusDrivenTeamRuntime(
        restarted_bridge,
        SQLiteOrderedResilientChoreographyStore(state_database),
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("live provider must not re-execute")
        ),
        max_attempts=1,
    )
    try:
        outcome = restarted.run_once()[0]
    finally:
        restarted_bridge.close()

    assert outcome.terminal is True
    assert outcome.acknowledged is True
    assert outcome.dead_lettered is False
    report = aggregate_runs(
        SQLiteTraceReader(trace_database),
        [team_run_id(request_id)],
    )
    assert report.success_count == 1
    assert report.total_model_calls >= 1
    assert report.unpriced_model_calls >= 1
    assert report.runs[0].terminal_event == "run.completed"
