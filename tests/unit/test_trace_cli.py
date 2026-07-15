from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paperclaw.cli import main
from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.trace import load_trace_jsonl


def _prepare_database(database: Path, secret: str) -> None:
    repository = SQLiteRepository(database)
    try:
        repository.create_conversation("conv-cli")
        repository.start_run(
            run_id="run-cli",
            conversation_id="conv-cli",
            agent_id="query_engine",
            role="agent",
        )
        session = SessionService(
            repository,
            conversation_id="conv-cli",
            run_id="run-cli",
            agent_id="query_engine",
        )
        session.emit(
            "model.failed",
            {
                "provider": "mistral",
                "model": "mistral-test",
                "error_code": "PROVIDER_ERROR",
                "error_message": f"Bearer {secret}",
            },
        )
        session.close(stop_reason="runtime_failed")
    finally:
        repository.close()


def test_trace_export_cli_is_read_only_and_redacts_env_key(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    secret = "cli-provider-secret"
    database = tmp_path / "paperclaw.db"
    output = tmp_path / "trace.jsonl"
    _prepare_database(database, secret)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    monkeypatch.setenv("PAPERCLAW_API_KEY", secret)

    exit_code = main(
        [
            "trace",
            "export",
            "--database",
            str(database),
            "--run-id",
            "run-cli",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    events = load_trace_jsonl(output, require_terminal=True)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["event_count"] == 2
    assert payload["first_sequence"] == 1
    assert payload["last_sequence"] == 2
    assert before == after
    assert secret not in output.read_text(encoding="utf-8")
    assert events[0].payload["error_message"] == "Bearer <REDACTED>"


def test_trace_export_cli_reports_unknown_run(
    tmp_path: Path,
    capsys,
) -> None:
    database = tmp_path / "paperclaw.db"
    _prepare_database(database, "unused-secret")

    exit_code = main(
        [
            "trace",
            "export",
            "--database",
            str(database),
            "--run-id",
            "run-missing",
            "--output",
            str(tmp_path / "missing.jsonl"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error_type"] == "TraceReadError"
    assert "run does not exist" in payload["error"]
