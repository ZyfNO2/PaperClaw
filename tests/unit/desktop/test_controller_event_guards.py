from __future__ import annotations

import json
from time import monotonic, sleep

from paperclaw.desktop.controller import DesktopController
from paperclaw.harness import RunResult


class GuardProbeEngine:
    def __init__(self) -> None:
        self.event_handler = None

    def submit(self, task, *, limits):
        self.event_handler("run.started", {"run_id": "run-a", "sequence": 1})
        self.event_handler(
            "model.started",
            {"run_id": "run-a", "sequence": 2, "call_index": 1},
        )
        self.event_handler(
            "tool.started",
            {"run_id": "run-a", "sequence": 2, "call_index": 1, "tool": "stale"},
        )
        self.event_handler(
            "tool.started",
            {"run_id": "run-b", "sequence": 3, "call_index": 1, "tool": "cross"},
        )
        self.event_handler(
            "future.secret.event",
            {
                "run_id": "run-a",
                "sequence": 3,
                "reasoning": "must-not-render",
                "tool_output": "must-not-render",
            },
        )
        self.event_handler(
            "run.completed",
            {
                "run_id": "run-a",
                "sequence": 4,
                "status": "completed",
                "stop_reason": "done",
                "model_calls": 1,
                "tool_calls": 0,
            },
        )
        return RunResult(
            run_id="run-a",
            status="completed",
            output="done",
            stop_reason="done",
            model_calls=1,
            tool_calls=0,
            last_event_sequence=4,
        )

    def request_stop(self, run_id, reason="user_requested"):
        return False


class GuardProbeFactory:
    def __init__(self) -> None:
        self.engine = GuardProbeEngine()

    def create(self, request, event_handler):
        self.engine.event_handler = event_handler
        return self.engine


def _wait_terminal(controller: DesktopController) -> dict:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        state = controller.get_state()["state"]
        if state["terminal"] and not state["active"]:
            return state
        sleep(0.01)
    raise AssertionError("controller did not reach terminal state")


def test_controller_reuses_reducer_stale_cross_run_and_unknown_event_guards(tmp_path) -> None:
    controller = DesktopController(runtime_factory=GuardProbeFactory())
    response = controller.start_run(
        {
            "task": "guard probe",
            "workspace": str(tmp_path),
            "base_url": "https://provider.invalid/v1",
            "api_key": "guard-test-secret",
            "model": "model-a",
        }
    )
    assert response["ok"] is True
    state = _wait_terminal(controller)
    assert state["status"] == "completed"
    assert state["last_sequence"] == 4
    assert state["tool_calls"] == 0

    items = controller.poll_events(500)["items"]
    events = [item["event"] for item in items if item["kind"] == "event"]
    assert [event["event_type"] for event in events] == [
        "run.started",
        "model.started",
        "future.secret.event",
        "run.completed",
    ]
    rendered = json.dumps(items)
    assert "stale" not in rendered
    assert "cross" not in rendered
    assert "must-not-render" not in rendered
    assert "guard-test-secret" not in rendered
