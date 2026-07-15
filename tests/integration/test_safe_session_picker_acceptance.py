"""End-to-end acceptance test for the v0.06.1 safe session picker.

This test exercises the full path that the TUI would take: a conversation is
opened through SessionService, safely closed, then reopened via TUI commands
bound to the same SQLite database. The new submission must create a fresh Run
under the same conversation_id while leaving the original ended Run untouched.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.harness import QueryEngine, RunLimits
from paperclaw.session_commands import open_persistent_session_runtime
from paperclaw.tui.app import PaperClawApp
from paperclaw.tui.bridge import TUIEventBridge
from paperclaw.tui.widgets import PromptInput
from tests.helpers import FakeModel, done


def test_tui_reopen_closed_session_creates_fresh_run_and_preserves_original(
    tmp_path: Path,
) -> None:
    database = tmp_path / "paperclaw.db"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Phase 1: create and safely close a conversation with a known run.
    repository = SQLiteRepository(database)
    session = SessionService.open(repository, conversation_id="conv-restart")
    session.append_message("user", "original task")
    session.append_message("assistant", "original result")
    original_run_id = session.run_id
    session.close(stop_reason="done")
    repository.close()

    # Phase 2: bind the TUI to the same database and reopen the conversation.
    runtime = open_persistent_session_runtime(database)
    model = FakeModel([done(result="continued result")])

    def factory(event_handler, conversation_id: str | None = None):
        bridge = TUIEventBridge(event_handler)
        executor = runtime.create_executor(
            model,
            workspace,
            enable_verification_gate=False,
            legacy_event_handler=bridge.handle_legacy_event,
        )
        return QueryEngine(
            executor,
            conversation_id=conversation_id or "tui-fresh",
            event_handler=bridge.handle_query_event,
        )

    async def scenario() -> None:
        app = PaperClawApp(
            engine_factory=factory,
            limits=RunLimits(),
            session_commands=runtime.commands,
        )
        async with app.run_test(size=(100, 24)) as pilot:
            prompt = app.query_one(PromptInput)
            for command in ("/sessions", "/preview 1", "/open 1"):
                prompt.value = command
                prompt.focus()
                await pilot.press("enter")
                await pilot.pause()

            assert app._conversation_id == "conv-restart"

            prompt.value = "continue with a fresh run"
            prompt.focus()
            await pilot.press("enter")

            for _ in range(50):
                await pilot.pause()
                if not app._run_in_flight:
                    break

            assert not app._run_in_flight
            assert app._reducer.snapshot.status == "completed"

    asyncio.run(scenario())
    runtime.close()

    # Phase 3: verify persistence invariants.
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT run_id, ended_at, stop_reason FROM runs "
            "WHERE conversation_id = ?",
            ("conv-restart",),
        ).fetchall()
        message_count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            ("conv-restart",),
        ).fetchone()

    runs = {
        str(run_id): {"ended_at": ended_at, "stop_reason": stop_reason}
        for run_id, ended_at, stop_reason in rows
    }

    assert len(runs) == 2
    assert original_run_id in runs
    new_run_ids = set(runs) - {original_run_id}
    assert len(new_run_ids) == 1
    new_run_id = new_run_ids.pop()

    assert runs[original_run_id]["ended_at"] is not None
    assert runs[original_run_id]["stop_reason"] == "done"
    assert runs[new_run_id]["ended_at"] is not None
    assert message_count is not None
    assert int(message_count[0]) == 4
