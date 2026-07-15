from __future__ import annotations

import asyncio

from paperclaw.context.session_picker import SessionMessagePreview
from paperclaw.harness import RunLimits
from paperclaw.session_commands import (
    SafeSessionPreview,
    SafeSessionSummary,
    SessionCommandAPI,
)
from paperclaw.tui.app import PaperClawApp
from paperclaw.tui.widgets import PromptInput


class FakeEngine:
    def submit(self, text, *, limits=None):  # pragma: no cover - not used here
        raise AssertionError("submit should not be called")

    def request_stop(self, run_id, reason="user_requested"):
        return False


class FakePicker:
    def __init__(self) -> None:
        self.summary = SafeSessionSummary(
            conversation_id="conversation-1",
            conversation_created_at="2026-07-15T00:00:00Z",
            latest_run_id="run-closed",
            latest_run_created_at="2026-07-15T00:00:00Z",
            latest_run_ended_at="2026-07-15T00:01:00Z",
            stop_reason="done",
            message_count=2,
        )
        self.preview = SafeSessionPreview(
            summary=self.summary,
            messages=(
                SessionMessagePreview(
                    role="user",
                    content="previous question",
                    created_at="2026-07-15T00:00:10Z",
                ),
                SessionMessagePreview(
                    role="assistant",
                    content="previous answer",
                    created_at="2026-07-15T00:00:20Z",
                ),
            ),
        )
        self.preview_calls = []

    def list_safe_sessions(self, *, limit=20):
        assert limit == 20
        return (self.summary,)

    def preview_safe_session(self, conversation_id, *, message_limit=8):
        self.preview_calls.append((conversation_id, message_limit))
        return self.preview


def test_tui_session_commands_select_conversation_for_fresh_engine() -> None:
    async def scenario() -> None:
        picker = FakePicker()
        factory_calls = []

        def factory(_handler, conversation_id=None):
            factory_calls.append(conversation_id)
            return FakeEngine()

        app = PaperClawApp(
            engine_factory=factory,
            limits=RunLimits(),
            session_commands=SessionCommandAPI(picker),
        )
        async with app.run_test(size=(100, 24)) as pilot:
            prompt = app.query_one(PromptInput)
            for command in ("/sessions", "/preview 1", "/open 1"):
                prompt.value = command
                prompt.focus()
                await pilot.press("enter")
                await pilot.pause()

            assert app._conversation_id == "conversation-1"
            assert factory_calls == [None, "conversation-1"]
            assert picker.preview_calls == [
                ("conversation-1", 8),
                ("conversation-1", 8),
            ]
            assert app._reducer.snapshot.status == "idle"

    asyncio.run(scenario())


def test_tui_session_commands_preview_and_open_by_conversation_id() -> None:
    async def scenario() -> None:
        picker = FakePicker()
        factory_calls = []

        def factory(_handler, conversation_id=None):
            factory_calls.append(conversation_id)
            return FakeEngine()

        app = PaperClawApp(
            engine_factory=factory,
            limits=RunLimits(),
            session_commands=SessionCommandAPI(picker),
        )
        async with app.run_test(size=(100, 24)) as pilot:
            prompt = app.query_one(PromptInput)
            for command in ("/preview conversation-1", "/open conversation-1"):
                prompt.value = command
                prompt.focus()
                await pilot.press("enter")
                await pilot.pause()

            assert app._conversation_id == "conversation-1"
            assert factory_calls == [None, "conversation-1"]
            assert picker.preview_calls == [
                ("conversation-1", 8),
                ("conversation-1", 8),
            ]
            assert app._reducer.snapshot.status == "idle"

    asyncio.run(scenario())


class EmptyPicker:
    def list_safe_sessions(self, *, limit=20):
        assert limit == 20
        return ()

    def preview_safe_session(self, conversation_id, *, message_limit=8):
        raise AssertionError("preview should not be called for an empty catalog")


def test_tui_sessions_command_handles_empty_safe_catalog() -> None:
    async def scenario() -> None:
        app = PaperClawApp(
            engine_factory=lambda _handler: FakeEngine(),
            limits=RunLimits(),
            session_commands=SessionCommandAPI(EmptyPicker()),
        )
        async with app.run_test(size=(100, 24)) as pilot:
            prompt = app.query_one(PromptInput)
            prompt.value = "/sessions"
            prompt.focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app._conversation_id is None
            assert app._session_summaries == ()
            assert app._reducer.snapshot.status == "idle"

    asyncio.run(scenario())
