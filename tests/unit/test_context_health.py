import json
from pathlib import Path

from paperclaw.cli import main
from paperclaw.context.health import inspect_sqlite_database
from paperclaw.context.migrations import CURRENT_SCHEMA_VERSION
from paperclaw.context.repository import SQLiteRepository


def test_health_check_reports_migrated_database(tmp_path: Path) -> None:
    database = tmp_path / "paperclaw.db"
    repository = SQLiteRepository(database, migrate=True)
    repository.close()

    report = inspect_sqlite_database(database)

    assert report.ok is True
    assert report.messages == ("ok",)
    assert report.schema_version == CURRENT_SCHEMA_VERSION
    assert report.error_code is None


def test_health_check_is_fail_closed_for_missing_and_corrupt_database(
    tmp_path: Path,
) -> None:
    missing = inspect_sqlite_database(tmp_path / "missing.db")
    assert missing.ok is False
    assert missing.error_code == "DATABASE_NOT_FOUND"

    corrupt_path = tmp_path / "corrupt.db"
    corrupt_path.write_bytes(b"not a sqlite database")
    corrupt = inspect_sqlite_database(corrupt_path, full=True)
    assert corrupt.ok is False
    assert corrupt.check == "integrity_check"
    assert corrupt.error_code == "SQLITE_DATABASE_ERROR"


def test_doctor_cli_outputs_structured_report(tmp_path: Path, capsys) -> None:
    database = tmp_path / "paperclaw.db"
    repository = SQLiteRepository(database, migrate=True)
    repository.close()

    exit_code = main(["doctor", "--database", str(database)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["check"] == "quick_check"
    assert payload["schema_version"] == CURRENT_SCHEMA_VERSION
