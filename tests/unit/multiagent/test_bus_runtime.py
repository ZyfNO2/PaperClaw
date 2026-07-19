from __future__ import annotations

import json
from pathlib import Path

from paperclaw.eval.aggregate import MeteredChatModel, ModelPrice, PricingTable, UsageCollector
from paperclaw.message_bus import SQLiteMessageBusStore
from paperclaw.models.base import ModelTurn
from paperclaw.multiagent.bus_runtime import (
    BusDrivenTeamRuntime,
    SQLiteChoreographyStateStore,
    TEAM_DLQ_TOPIC,
    TEAM_EVENT_TOPIC,
    TEAM_REQUEST_TOPIC,
    TeamRunRequest,
)
from paperclaw.multiagent.contracts import AgentTask, TeamBudget
from paperclaw.multiagent.coordinator import Coordinator


class FakeModel:
    def __init__(self):
        self.used = False

    def complete(self, prompt: str) -> ModelTurn:
        if self.used:
            raise AssertionError("unexpected second model call")
        self.used = True
        return ModelTurn(
            content=json.dumps(
                {
                    "action": "done",
                    "arguments": {
                        "result": "complete",
                        "verification": "checked",
                        "remaining_issues": [],
                    },
                    "reason": "complete bounded task",
                }
            ),
            metadata={
                "provider": "fake",
                "model": "deterministic",
                "input_tokens": 10,
                "output_tokens": 5,
            },
        )


def make_request(request_id="req-1"):
    return TeamRunRequest(
        request_id=request_id,
        user_goal="complete two independent checks",
        tasks=(
            AgentTask(
                task_id="a",
                title="check a",
                objective="check a",
                acceptance_criteria=["complete"],
                allowed_paths=["."],
                allowed_tools=[],
                max_steps=3,
            ),
            AgentTask(
                task_id="b",
                title="check b",
                objective="check b",
                acceptance_criteria=["complete"],
                allowed_paths=["."],
                allowed_tools=[],
                max_steps=3,
            ),
        ),
        budget=TeamBudget(max_agents=2, max_total_steps=10, max_total_model_calls=10),
    )


def test_bus_drives_coordinator_publishes_events_metrics_and_acks(tmp_path: Path):
    bus = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    states = SQLiteChoreographyStateStore(tmp_path / "state.sqlite3")
    pricing = PricingTable([ModelPrice("fake", "deterministic", 1, 2)])

    def factory(budget, event_handler, usage):
        return Coordinator(
            lambda _agent_id: MeteredChatModel(FakeModel(), usage),
            tmp_path,
            budget=budget,
            enable_verification_gate=False,
            event_handler=event_handler,
        )

    runtime = BusDrivenTeamRuntime(
        bus,
        states,
        factory,
        usage_factory=lambda: UsageCollector(pricing),
    )
    outcome = runtime.execute(make_request())

    assert outcome.terminal is True
    assert outcome.acknowledged is True
    assert outcome.dead_lettered is False
    assert outcome.result is not None
    assert outcome.metrics["succeeded"] is True, outcome.to_dict()
    assert outcome.metrics["model_calls"] == 2
    assert outcome.metrics["input_tokens"] == 20
    assert outcome.metrics["output_tokens"] == 10
    assert outcome.metrics["estimated_cost_usd"] == 0.00004
    assert bus.get_cursor(runtime.consumer_id, TEAM_REQUEST_TOPIC).ack_sequence == 1

    events = bus.pull("audit", TEAM_EVENT_TOPIC, limit=1000)
    types = [message.payload["event_type"] for message in events]
    assert "team.started" in types
    assert "team.run.metrics" in types
    assert "team.run.terminal" in types
    assert states.get(runtime.consumer_id, outcome.request_message_id).terminal is True


def test_exact_submit_retry_reuses_request_message(tmp_path: Path):
    bus = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    states = SQLiteChoreographyStateStore(tmp_path / "state.sqlite3")

    def factory(budget, event_handler, usage):
        return Coordinator(
            lambda _agent_id: FakeModel(),
            tmp_path,
            budget=budget,
            enable_verification_gate=False,
            event_handler=event_handler,
        )

    runtime = BusDrivenTeamRuntime(bus, states, factory)
    first = runtime.submit(make_request())
    second = runtime.submit(make_request())
    assert first.message_id == second.message_id
    assert first.sequence == second.sequence == 1


def test_poison_request_retries_then_moves_to_dlq_and_acks(tmp_path: Path):
    bus = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    states = SQLiteChoreographyStateStore(tmp_path / "state.sqlite3")

    def broken_factory(budget, event_handler, usage):
        raise RuntimeError("provider setup failed")

    runtime = BusDrivenTeamRuntime(bus, states, broken_factory, max_attempts=2)
    message = runtime.submit(make_request("poison-1"))

    first = runtime.run_once()[0]
    assert first.terminal is False
    assert first.acknowledged is False
    assert bus.get_cursor(runtime.consumer_id, TEAM_REQUEST_TOPIC).ack_sequence == 0

    second = runtime.run_once()[0]
    assert second.terminal is True
    assert second.dead_lettered is True
    assert second.acknowledged is True
    assert second.failure_category == "runtimeerror"
    assert bus.get_cursor(runtime.consumer_id, TEAM_REQUEST_TOPIC).ack_sequence == message.sequence

    dlq = bus.pull("operator", TEAM_DLQ_TOPIC)
    assert len(dlq) == 1
    assert dlq[0].payload["event_type"] == "team.run.dead_lettered"
    assert dlq[0].payload["attempt"] == 2
