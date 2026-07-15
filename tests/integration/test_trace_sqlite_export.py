from __future__ import annotations

from pathlib import Path

from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.trace import (
    RepositoryTraceReader,
    TraceRedactor,
    export_trace_jsonl,
    load_trace_jsonl,
)


def test_sqlite_trace_export_round_trip(tmp_path: Path) -> None:
    secret = "live-provider-secret"
    database = tmp_path / "paperclaw.db"
    output = tmp_path / "trace.jsonl"
    repository = SQLiteRepository(database)
    try:
        repository.create_conversation("conv-1")
        repository.start_run(
            run_id="run-1",
            conversation_id="conv-1",
            agent_id="query_engine",
            role="agent",
        )
        session = SessionService(
            repository,
            conversation_id="conv-1",
            run_id="run-1",
            agent_id="query_engine",
        )
        session.emit(
            "model.started",
            {
                "provider": "mistral",
                "model": "mistral-test",
                "authorization": f"Bearer {secret}",
            },
        )
        session.emit(
            "model.completed",
            {
                "provider": "mistral",
                "model": "mistral-test",
                "duration_ms": 25,
            },
        )
        session.close(stop_reason="done")

        reader = RepositoryTraceReader(
            repository,
            redactor=TraceRedactor(secret_values=[secret]),
        )
        summary = export_trace_jsonl(
            reader,
            "run-1",
            output,
            require_terminal=True,
        )
        loaded = load_trace_jsonl(output, require_terminal=True)
    finally:
        repository.close()

    assert summary.event_count == 3
    assert summary.first_sequence == 1
    assert summary.last_sequence == 3
    assert len(summary.sha256) == 64
    assert [event.event_type for event in loaded] == [
        "model.started",
        "model.completed",
        "run.completed",
    ]
    assert [event.sequence for event in loaded] == [1, 2, 3]
    assert loaded[-1].status == "completed"
    assert loaded[-1].payload["source_event_type"] == "flow.stopped"
    assert secret not in output.read_text(encoding="utf-8")
    assert loaded[0].payload["authorization"] == "<REDACTED>"
