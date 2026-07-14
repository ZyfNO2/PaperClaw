import asyncio
import threading

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


class BlockingEngine:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.started = threading.Event()
        self.release = threading.Event()
        self.submit_calls = 0
        self.stop_requests = []

    def submit(self, text, *, limits=None):
        self.submit_calls += 1
        self.handler("run.started", {"run_id": "run-blocked", "sequence": 1})
        self.started.set()
        self.release.wait(timeout=2)
        self.handler(
            "run.stopped",
            {
                "run_id": "run-blocked",
                "sequence": 3,
                "status": "stopped",
                "stop_reason": "user_requested",
                "model_calls": 0,
                "tool_calls": 0,
            },
        )
        return RunResult(
            "run-blocked", "stopped", None, "user_requested", 0, 0, 3
        )

    def request_stop(self, run_id, reason="user_requested"):
        self.stop_requests.append((run_id, reason))
        self.handler(
            "run.stop_requested",
            {"run_id": run_id, "sequence": 2, "reason": reason},
        )
        self.release.set()
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


def test_active_run_rejects_duplicate_submit_and_accepts_cancel() -> None:
    async def scenario() -> None:
        engines = []

        def factory(handler):
            engine = BlockingEngine(handler)
            engines.append(engine)
            return engine

        app = PaperClawApp(engine_factory=factory, limits=RunLimits())
        async with app.run_test(size=(100, 24)) as pilot:
            prompt = app.query_one(PromptInput)
            prompt.value = "long task"
            prompt.focus()
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if engines[0].started.is_set() and app._active_run_id:
                    break

            prompt.value = "second task"
            await pilot.press("enter")
            assert engines[0].submit_calls == 1

            prompt.value = "/cancel"
            await pilot.press("enter")
            for _ in range(30):
                await pilot.pause()
                if not app._run_in_flight:
                    break

            assert engines[0].stop_requests == [
                ("run-blocked", "user_requested")
            ]
            assert app._reducer.snapshot.status == "stopped"
            assert app._reducer.snapshot.stop_reason == "user_requested"

    asyncio.run(scenario())
