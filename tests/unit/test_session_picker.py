from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.context.session_picker import SafeSessionPicker, SessionPickerError
from paperclaw.tui.commands import SessionCommandAPI


def test_picker_lists_only_conversations_without_active_runs(tmp_path: Path) -> None:
    database = tmp_path / "paperclaw.db"
    repository = SQLiteRepository(database)

    closed = SessionService.open(repository, conversation_id="closed-conversation")
    closed.append_message("user", "first question")
    closed.append_message("assistant", "first answer")
    closed.close(stop_reason="done")

    active = SessionService.open(repository, conversation_id="active-conversation")
    active.append_message("user", "still running")

    picker = SafeSessionPicker(database)
    summaries = picker.list_safe_sessions()

    assert [summary.conversation_id for summary in summaries] == [
        "closed-conversation"
    ]
    assert summaries[0].latest_run_id == closed.run_id
    assert summaries[0].stop_reason == "done"
    assert summaries[0].message_count == 2

    active.close(stop_reason="cancelled")
    repository.close()


def test_preview_and_reopen_are_read_only_and_revalidate_safety(
    tmp_path: Path,
) -> None:
    database = tmp_path / "paperclaw.db"
    repository = SQLiteRepository(database)
    session = SessionService.open(repository, conversation_id="conversation-1")
    session.append_message("user", "  inspect\nthis session  ")
    session.append_message("assistant", "safe preview")
    session.close(stop_reason="completed_verified")

    commands = SessionCommandAPI(SafeSessionPicker(database))
    before = _run_count(database)
    preview = commands.preview("conversation-1")
    reopened = commands.reopen("conversation-1")
    after = _run_count(database)

    assert preview.summary.latest_run_id == session.run_id
    assert [message.content for message in preview.messages] == [
        "inspect this session",
        "safe preview",
    ]
    assert reopened.conversation_id == "conversation-1"
    assert reopened.preview == preview
    assert before == after == 1

    repository.start_run(
        run_id="run-active",
        conversation_id="conversation-1",
        agent_id="test",
        role="agent",
    )
    with pytest.raises(SessionPickerError, match="not safely closed"):
        commands.reopen("conversation-1")

    repository.end_run("run-active", stop_reason="cancelled")
    repository.close()


def test_picker_fails_closed_for_missing_database(tmp_path: Path) -> None:
    picker = SafeSessionPicker(tmp_path / "missing.db")
    with pytest.raises(SessionPickerError, match="does not exist"):
        picker.list_safe_sessions()


def _run_count(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT COUNT(*) FROM runs").fetchone()
    assert row is not None
    return int(row[0])
