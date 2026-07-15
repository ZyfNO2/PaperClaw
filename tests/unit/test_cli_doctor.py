"""Acceptance tests for the CLI ``doctor`` subcommand."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paperclaw.cli import main
from paperclaw.context.health import inspect_sqlite_database
from paperclaw.context.migrations import CURRENT_SCHEMA_VERSION
from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import open_session


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_doctor_outputs_structured_json_and_does_not_mutate_database(
    tmp_path: Path, capsys
) -> None:
    """``doctor`` prints a JSON report and leaves the database bytes unchanged."""

    database = tmp_path / "paperclaw.db"
    repo, session = open_session(str(database), conversation_id="conv-doctor")
    session.close(stop_reason="done")
    repo.close()

    before = _sha256(database)
    exit_code = main(["doctor", "--database", str(database)])
    captured = capsys.readouterr()
    after = _sha256(database)

    assert exit_code == 0
    assert before == after, "doctor mutated the database file"

    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["check"] == "quick_check"
    assert payload["schema_version"] == CURRENT_SCHEMA_VERSION
    assert payload["path"] == str(database.resolve())


def test_doctor_full_runs_integrity_check(tmp_path: Path, capsys) -> None:
    """``doctor --full`` selects integrity_check and surfaces the flag in JSON."""

    database = tmp_path / "paperclaw.db"
    repo, session = open_session(str(database), conversation_id="conv-doctor-full")
    session.close(stop_reason="done")
    repo.close()

    before = _sha256(database)
    exit_code = main(["doctor", "--database", str(database), "--full"])
    captured = capsys.readouterr()
    after = _sha256(database)

    assert exit_code == 0
    assert before == after, "doctor --full mutated the database file"

    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["check"] == "integrity_check"
    assert payload["full"] is True
    assert payload["schema_version"] == CURRENT_SCHEMA_VERSION


def test_doctor_report_matches_programmatic_inspection(tmp_path: Path, capsys) -> None:
    """CLI output is consistent with the underlying health inspection API."""

    database = tmp_path / "paperclaw.db"
    repo = SQLiteRepository(database, migrate=True)
    repo.close()

    exit_code = main(["doctor", "--database", str(database), "--full"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    report = inspect_sqlite_database(database, full=True)

    assert exit_code == 0
    assert payload["ok"] == report.ok
    assert payload["check"] == report.check
    assert payload["schema_version"] == report.schema_version
    assert payload["full"] is True
