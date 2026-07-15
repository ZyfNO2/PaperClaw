from __future__ import annotations

from pathlib import Path

from paperclaw.context.repository import SQLiteRepository
from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.trace import RepositoryTraceReader
from tests.helpers import FakeModel, done


def test_query_engine_run_projects_to_canonical_durable_trace(
    tmp_path: Path,
) -> None:
    repository = SQLiteRepository(tmp_path / "paperclaw.db", migrate=True)
    try:
        executor = AgentRuntimeExecutor(
            FakeModel([done(result="trace-ok")]),
            tmp_path,
            repository=repository,
            enable_verification_gate=False,
        )
        result = QueryEngine(
            executor,
            conversation_id="conv-trace-runtime",
        ).submit(
            "finish directly",
            limits=RunLimits(
                max_steps=3,
                max_model_calls=2,
                max_tool_calls=2,
            ),
        )

        raw_events = repository.list_events(result.run_id)
        trace = RepositoryTraceReader(repository).get_run_trace(
            result.run_id,
            require_terminal=True,
        )
    finally:
        repository.close()

    assert [event.event_type for event in raw_events] == [
        "run.started",
        "model.started",
        "model.completed",
        "flow.stopped",
    ]
    assert [event.sequence for event in raw_events] == [1, 2, 3, 4]
    assert raw_events[0].payload["query_event_sequence"] == 1
    assert raw_events[0].payload["limits"] == {
        "max_steps": 3,
        "max_model_calls": 2,
        "max_tool_calls": 2,
    }
    assert raw_events[1].payload["query_event_sequence"] == 2
    assert raw_events[2].payload["query_event_sequence"] == 3

    assert [event.event_type for event in trace] == [
        "run.started",
        "model.started",
        "model.completed",
        "run.completed",
    ]
    assert trace[0].component == "harness"
    assert trace[0].status == "started"
    assert trace[-1].status == "completed"
    assert trace[-1].payload["stop_reason"] == "done"
    assert trace[-1].payload["source_event_type"] == "flow.stopped"
