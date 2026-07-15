from __future__ import annotations

import hashlib
from pathlib import Path

from paperclaw.context.repository import SQLiteRepository
from paperclaw.eval import EvalThresholds, evaluate_trace
from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.replay import replay_recorded_trace
from paperclaw.trace import (
    SQLiteTraceReader,
    export_trace_jsonl,
    inspect_run_trace,
    load_trace_jsonl,
)
from tests.helpers import FakeModel, action, done


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_full_runtime_trace_inspect_replay_eval_export_pipeline(
    tmp_path: Path,
) -> None:
    database = tmp_path / "paperclaw.db"
    output = tmp_path / "trace.jsonl"
    task = "create pipeline.txt and finish"
    file_content = "PaperClaw full trace pipeline OK\n"
    repository = SQLiteRepository(database, migrate=True)
    try:
        model = FakeModel(
            [
                action(
                    "file_write",
                    {
                        "path": "pipeline.txt",
                        "content": file_content,
                        "overwrite": False,
                    },
                ),
                done(result="pipeline-complete"),
            ]
        )
        result = QueryEngine(
            AgentRuntimeExecutor(
                model,
                tmp_path,
                repository=repository,
                enable_verification_gate=False,
            ),
            conversation_id="conv-full-pipeline",
        ).submit(
            task,
            limits=RunLimits(
                max_steps=4,
                max_model_calls=3,
                max_tool_calls=2,
            ),
        )
    finally:
        repository.close()

    assert result.status == "completed"
    assert result.output == "pipeline-complete"
    assert (tmp_path / "pipeline.txt").read_text(encoding="utf-8") == file_content

    database_before = _sha256(database)
    reader = SQLiteTraceReader(database)
    trace = reader.get_run_trace(result.run_id, require_terminal=True)
    inspection = inspect_run_trace(reader, result.run_id)
    replay = replay_recorded_trace(reader, result.run_id, strict=True)
    evaluation = evaluate_trace(
        reader,
        result.run_id,
        thresholds=EvalThresholds(
            require_completed=True,
            require_replay_faithful=True,
            max_tool_failure_rate=0.0,
            max_retries=0,
            max_errors=0,
        ),
    )
    export = export_trace_jsonl(
        reader,
        result.run_id,
        output,
        require_terminal=True,
    )
    loaded = load_trace_jsonl(output, require_terminal=True)
    database_after = _sha256(database)

    event_types = [event.event_type for event in trace]
    assert event_types[0] == "run.started"
    assert event_types[-1] == "run.completed"
    assert event_types.count("model.started") == 2
    assert event_types.count("model.completed") == 2
    assert event_types.count("tool.started") == 1
    assert event_types.count("tool.completed") == 1

    assert inspection.terminal_event == "run.completed"
    assert inspection.model_calls == 2
    assert inspection.tool_calls == 1
    assert inspection.error_count == 0
    assert replay.faithful is True
    assert replay.issue_count == 0
    assert evaluation.overall_passed is True
    assert evaluation.failed_checks == ()

    assert export.event_count == len(trace)
    assert loaded == trace
    assert database_before == database_after

    encoded = output.read_text(encoding="utf-8")
    assert task not in encoded
    assert file_content.strip() not in encoded
    assert "pipeline.txt" not in encoded
