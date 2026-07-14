import asyncio

from paperclaw.harness import RunLimits, RunResult
from paperclaw.tui.app import PaperClawApp
from paperclaw.tui.widgets import ChatLog, PromptInput, RunStatus, ToolTimeline


class FakeEngine:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.stop_requests = []

    def submit(self, text, *, limits=None):
        self.handler("run.started", {"run_id": "run-test", "sequence": 1})
        self.handler(
            "model.started",
            {"run_id": "run-test", "sequence": 2, "call_index": 1},
        )
        self.handler(
            "verification.completed",
            {
                "run_id": "run-test",
                "sequence": 3,
                "result": {"status": "passed"},
            },
        )
        self.handler(
            "run.completed",
            {
                "run_id": "run-test",
                "sequence": 4,
                "status": "completed",
                "stop_reason": "done",
                "model_calls": 1,
                "tool_calls": 0,
            },
        )
        return RunResult("run-test", "completed", "ok", "done", 1, 0, 4)

    def request_stop(self, run_id, reason="user_requested"):
        self.stop_requests.append((run_id, reason))
        return True


def test_headless_launch_submit_and_narrow_layout() -> None:
    async def scenario() -> None:
        app = PaperClawApp(
            engine_factory=lambda handler: FakeEngine(handler),
            limits=RunLimits(),
        )
        async with app.run_test(size=(60, 20)) as pilot:
            assert app.query_one(ChatLog)
            assert app.query_one(PromptInput)
            assert app.query_one(RunStatus)
            assert app.query_one(ToolTimeline)
            assert app.query_one("#main").has_class("narrow")

            prompt = app.query_one(PromptInput)
            prompt.value = "do work"
            prompt.focus()
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if not app._run_in_flight:
                    break
            assert app._reducer.snapshot.status == "completed"
            assert app._reducer.snapshot.last_sequence == 4

    asyncio.run(scenario())
