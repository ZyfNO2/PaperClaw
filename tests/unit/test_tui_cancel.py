"""TUI-level acceptance test for the v0.06 cooperative cancel race fix."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.tools.base import ToolContext, ToolResult
from paperclaw.tools.registry import ToolRegistry
from paperclaw.tui.app import PaperClawApp
from paperclaw.tui.widgets import PromptInput
from tests.helpers import FakeModel, action


class BlockingCancelTool:
    """Block until released, then raise to simulate an in-flight tool failure."""

    name = "blocking_cancel"
    description = "Block until released, then raise."

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def validate(self, arguments: dict) -> None:
        return None

    def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        self.started.set()
        assert self.release.wait(timeout=2)
        raise RuntimeError("tool execution ended after cancellation")


def test_tui_cancel_during_tool_execution_maps_to_stopped(tmp_path: Path) -> None:
    """/cancel while a tool is executing leaves the run as stopped/user_requested."""

    tool = BlockingCancelTool()
    raw_events: list[tuple[str, dict]] = []

    def make_engine(handler):
        def wrapped_handler(event_type: str, payload: dict) -> None:
            raw_events.append((event_type, dict(payload)))
            handler(event_type, payload)

        return QueryEngine(
            AgentRuntimeExecutor(
                FakeModel([action("blocking_cancel", {})]),
                tmp_path,
                registry=ToolRegistry([tool]),
                enable_verification_gate=False,
            ),
            conversation_id="conv-tui-cancel",
            event_handler=wrapped_handler,
        )

    async def scenario() -> None:
        app = PaperClawApp(engine_factory=make_engine, limits=RunLimits())
        async with app.run_test(size=(100, 24)) as pilot:
            prompt = app.query_one(PromptInput)
            prompt.value = "run blocking tool"
            prompt.focus()
            await pilot.press("enter")

            for _ in range(50):
                await pilot.pause()
                if tool.started.is_set() and app._active_run_id is not None:
                    break

            assert tool.started.is_set(), "tool execution never started"
            assert app._active_run_id is not None, "run id was not set"

            prompt.value = "/cancel"
            await pilot.press("enter")

            tool.release.set()
            for _ in range(50):
                await pilot.pause()
                if not app._run_in_flight:
                    break

            assert not app._run_in_flight, "run never finished after cancel"
            assert app._reducer.snapshot.status == "stopped"
            assert app._reducer.snapshot.stop_reason == "user_requested"

    asyncio.run(scenario())

    assert any(
        event_type == "tool.failed"
        and payload.get("error_code") == "TOOL_EXECUTION_FAILED"
        for event_type, payload in raw_events
    )

    terminal = [
        event_type
        for event_type, _ in raw_events
        if event_type in {"run.completed", "run.failed", "run.stopped"}
    ]
    assert terminal == ["run.stopped"]
