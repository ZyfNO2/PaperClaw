from __future__ import annotations

import json
from pathlib import Path

from paperclaw.eval.aggregate import MeteredChatModel, ModelPrice, PricingTable, aggregate_runs
from paperclaw.eval.cli import main as observe_main
from paperclaw.message_bus import SQLiteMessageBusStore
from paperclaw.models.base import ModelTurn
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


class ScriptedModel:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)

    def complete(self, prompt: str) -> ModelTurn:
        if not self._responses:
            raise AssertionError("unexpected extra model call")
        payload = self._responses.pop(0)
        return ModelTurn(
            content=json.dumps(payload),
            metadata={
                "provider": "fake",
                "model": "deterministic",
                "input_tokens": 10,
                "output_tokens": 5,
            },
        )


def _done(result: str = "complete") -> dict:
    return {
        "action": "done",
        "arguments": {
            "result": result,
            "verification": "checked",
            "remaining_issues": [],
        },
        "reason": "complete bounded task",
    }


def _request(request_id: str, *, tool: bool = False) -> TeamRunRequest:
    return TeamRunRequest(
        request_id=request_id,
        user_goal="complete one observable check",
        tasks=(
            AgentTask(
                task_id="check",
                title="observable check",
                objective="complete the bounded observable check",
                acceptance_criteria=["returns a structured done action"],
                allowed_paths=["note.txt"] if tool else ["."],
                allowed_tools=["file_read"] if tool else [],
                max_steps=3,
            ),
        ),
        budget=TeamBudget(
            max_agents=1,
            max_total_steps=3,
            max_total_model_calls=3,
            max_fix_rounds=0,
        ),
    )


def _execute(
    tmp_path: Path,
    request: TeamRunRequest,
    model: ScriptedModel,
):
    bus = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    trace_database = tmp_path / "traces.sqlite3"
    bridge = SQLiteTeamTraceBridge(bus, trace_database)
    states = SQLiteChoreographyStateStore(tmp_path / "state.sqlite3")
    pricing = PricingTable([ModelPrice("fake", "deterministic", 1, 2)])

    def factory(budget, event_handler, usage):
        return ObservedCoordinator(
            lambda _agent_id: MeteredChatModel(model, usage),
            tmp_path,
            budget=budget,
            enable_verification_gate=False,
            event_handler=event_handler,
        )

    runtime = BusDrivenTeamRuntime(
        bridge,
        states,
        factory,
        usage_factory=lambda: TraceUsageCollector(
            pricing,
            bridge,
            request.request_id,
        ),
    )
    outcome = runtime.execute(request)
    bridge.close()
    return outcome, trace_database, pricing


def test_team_run_is_queryable_by_existing_trace_and_eval(tmp_path: Path):
    request = _request("trace-closure")
    outcome, trace_database, pricing = _execute(tmp_path, request, ScriptedModel([_done()]))

    assert outcome.terminal is True
    assert outcome.metrics["succeeded"] is True

    reader = SQLiteTraceReader(trace_database)
    events = reader.get_run_trace(team_run_id(request.request_id), require_terminal=True)
    event_types = [event.event_type for event in events]
    assert event_types[0] == "run.started"
    assert "team.request.published" in event_types
    assert "model.started" in event_types
    assert "model.completed" in event_types
    assert "run.metrics" in event_types
    assert event_types[-1] == "run.completed"

    report = aggregate_runs(reader, [team_run_id(request.request_id)], pricing=pricing)
    assert report.run_count == 1
    assert report.success_count == 1
    assert report.total_model_calls == 1
    assert report.total_tokens == 15
    assert report.total_estimated_cost_usd == 0.00002
    assert report.unpriced_model_calls == 0


def test_observed_worker_projects_tool_lifecycle_into_trace(tmp_path: Path):
    (tmp_path / "note.txt").write_text("trace me", encoding="utf-8")
    request = _request("tool-trace", tool=True)
    model = ScriptedModel(
        [
            {
                "action": "file_read",
                "arguments": {"path": "note.txt"},
                "reason": "read bounded evidence",
            },
            _done("read complete"),
        ]
    )
    outcome, trace_database, pricing = _execute(tmp_path, request, model)

    assert outcome.metrics["tool_call_count"] == 1
    reader = SQLiteTraceReader(trace_database)
    events = reader.get_run_trace(team_run_id(request.request_id), require_terminal=True)
    tool_events = [event for event in events if event.component == "tool"]
    assert [event.event_type for event in tool_events] == ["tool.started", "tool.completed"]
    assert tool_events[0].payload["tool"] == "file_read"
    assert tool_events[1].status == "completed"

    report = aggregate_runs(reader, [team_run_id(request.request_id)], pricing=pricing)
    assert report.total_model_calls == 2
    assert report.total_tool_calls == 1
    assert report.total_tool_failures == 0
    assert report.total_tokens == 30


def test_observe_cli_resolves_team_request_id(tmp_path: Path, capsys):
    request = _request("request-id-query")
    _, trace_database, _ = _execute(tmp_path, request, ScriptedModel([_done()]))
    pricing_path = tmp_path / "pricing.json"
    pricing_path.write_text(
        json.dumps(
            {
                "prices": [
                    {
                        "provider": "fake",
                        "model": "deterministic",
                        "input_per_million_usd": 1,
                        "output_per_million_usd": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = observe_main(
        [
            "--database",
            str(trace_database),
            "--request-id",
            request.request_id,
            "--pricing",
            str(pricing_path),
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["run_count"] == 1
    assert report["runs"][0]["run_id"] == team_run_id(request.request_id)
    assert report["success_rate"] == 1.0
