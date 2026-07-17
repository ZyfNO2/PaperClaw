from __future__ import annotations

import json
from threading import Event, Lock
from time import monotonic, sleep

from paperclaw.desktop.controller import DesktopController
from paperclaw.harness import RunResult


def _request(tmp_path, *, api_key: str = "controller-secret") -> dict:
    return {
        "task": "perform one deterministic task",
        "workspace": str(tmp_path),
        "base_url": "https://provider.invalid/v1",
        "api_key": api_key,
        "model": "model-a",
        "provider": "provider-a",
    }


class StaticFactory:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.last_request = None

    def create(self, request, event_handler):
        self.last_request = request
        self.engine.event_handler = event_handler
        return self.engine


class SuccessfulEngine:
    def __init__(self) -> None:
        self.event_handler = None

    def submit(self, task, *, limits):
        assert task == "perform one deterministic task"
        self.event_handler("run.started", {"run_id": "run-success", "sequence": 1})
        self.event_handler(
            "model.started",
            {"run_id": "run-success", "sequence": 2, "call_index": 1},
        )
        self.event_handler(
            "model.completed",
            {"run_id": "run-success", "sequence": 3, "call_index": 1},
        )
        self.event_handler(
            "verification.completed",
            {
                "run_id": "run-success",
                "sequence": 4,
                "result": {"status": "passed", "summary": "all checks passed"},
            },
        )
        self.event_handler(
            "run.completed",
            {
                "run_id": "run-success",
                "sequence": 5,
                "status": "completed",
                "stop_reason": "done",
                "model_calls": 1,
                "tool_calls": 0,
            },
        )
        return RunResult(
            run_id="run-success",
            status="completed",
            output="finished result",
            stop_reason="done",
            model_calls=1,
            tool_calls=0,
            last_event_sequence=5,
        )

    def request_stop(self, run_id, reason="user_requested"):
        return False


class BlockingEngine:
    def __init__(self) -> None:
        self.event_handler = None
        self.started = Event()
        self.release = Event()
        self.stop_requested = False
        self._sequence = 0
        self._lock = Lock()

    def _emit(self, event_type: str, payload: dict) -> None:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        self.event_handler(
            event_type,
            {"run_id": "run-blocking", "sequence": sequence, **payload},
        )

    def submit(self, task, *, limits):
        self._emit("run.started", {})
        self.started.set()
        assert self.release.wait(timeout=3)
        if self.stop_requested:
            self._emit(
                "run.stopped",
                {
                    "status": "stopped",
                    "stop_reason": "user_requested",
                    "model_calls": 0,
                    "tool_calls": 0,
                },
            )
            status = "stopped"
            reason = "user_requested"
        else:
            self._emit(
                "run.completed",
                {
                    "status": "completed",
                    "stop_reason": "done",
                    "model_calls": 0,
                    "tool_calls": 0,
                },
            )
            status = "completed"
            reason = "done"
        return RunResult(
            run_id="run-blocking",
            status=status,
            output=None,
            stop_reason=reason,
            model_calls=0,
            tool_calls=0,
            last_event_sequence=self._sequence,
        )

    def request_stop(self, run_id, reason="user_requested"):
        assert run_id == "run-blocking"
        if self.stop_requested:
            return False
        self.stop_requested = True
        self._emit("run.stop_requested", {"reason": reason})
        self.release.set()
        return True


class ProviderFailureEngine:
    def __init__(self) -> None:
        self.event_handler = None

    def submit(self, task, *, limits):
        self.event_handler("run.started", {"run_id": "run-failed", "sequence": 1})
        self.event_handler(
            "model.failed",
            {
                "run_id": "run-failed",
                "sequence": 2,
                "call_index": 1,
                "error_code": "AUTHENTICATION_FAILED",
                "error_message": "raw provider detail must not render",
            },
        )
        self.event_handler(
            "run.failed",
            {
                "run_id": "run-failed",
                "sequence": 3,
                "status": "failed",
                "stop_reason": "executor_failed",
                "model_calls": 1,
                "tool_calls": 0,
            },
        )
        return RunResult(
            run_id="run-failed",
            status="failed",
            output=None,
            stop_reason="executor_failed",
            model_calls=1,
            tool_calls=0,
            last_event_sequence=3,
        )

    def request_stop(self, run_id, reason="user_requested"):
        return False


class FailingFactory:
    def create(self, request, event_handler):
        raise RuntimeError(f"construction failed with {request.api_key}")


def _wait_for(controller: DesktopController, predicate, timeout: float = 3.0) -> dict:
    deadline = monotonic() + timeout
    last = controller.get_state()["state"]
    while monotonic() < deadline:
        last = controller.get_state()["state"]
        if predicate(last):
            return last
        sleep(0.01)
    raise AssertionError(f"condition not reached; last state={last!r}")


def test_controller_completes_fake_run_and_projects_safe_state(tmp_path) -> None:
    controller = DesktopController(runtime_factory=StaticFactory(SuccessfulEngine()))
    assert controller.start_run(_request(tmp_path)) == {
        "ok": True,
        "accepted": True,
        "status": "starting",
    }
    state = _wait_for(controller, lambda value: value["terminal"] and not value["active"])
    assert state["status"] == "completed"
    assert state["final_result"] == "finished result"
    assert state["verification_status"] == "passed"
    assert state["verification_summary"] == "all checks passed"
    assert state["model_calls"] == 1

    items = controller.poll_events(500)["items"]
    event_types = [item["event"]["event_type"] for item in items if item["kind"] == "event"]
    assert event_types == [
        "run.started",
        "model.started",
        "model.completed",
        "verification.completed",
        "run.completed",
    ]
    assert "controller-secret" not in json.dumps(items)


def test_controller_rejects_duplicate_submit_and_cancels_active_run(tmp_path) -> None:
    engine = BlockingEngine()
    controller = DesktopController(runtime_factory=StaticFactory(engine))
    assert controller.start_run(_request(tmp_path))["ok"] is True
    assert engine.started.wait(timeout=2)

    duplicate = controller.start_run(_request(tmp_path, api_key="second-secret"))
    assert duplicate["ok"] is False
    assert duplicate["error_code"] == "run_already_active"

    cancelled = controller.cancel_run()
    assert cancelled == {"ok": True, "accepted": True, "status": "stopping"}
    state = _wait_for(controller, lambda value: value["terminal"] and not value["active"])
    assert state["status"] == "stopped"
    assert state["stop_reason"] == "user_requested"
    assert controller.cancel_run()["error_code"] == "run_not_active"


def test_controller_maps_provider_failure_without_raw_exception_text(tmp_path) -> None:
    controller = DesktopController(runtime_factory=StaticFactory(ProviderFailureEngine()))
    controller.start_run(_request(tmp_path))
    state = _wait_for(controller, lambda value: value["terminal"] and not value["active"])
    assert state["status"] == "failed"
    assert state["error_code"] == "provider_authentication_error"
    assert state["error_message"] == "Provider authentication failed."
    rendered = json.dumps(controller.poll_events(500))
    assert "raw provider detail" not in rendered


def test_controller_sanitizes_secret_bearing_factory_failure(tmp_path) -> None:
    secret = "factory-secret-value"
    controller = DesktopController(runtime_factory=FailingFactory())
    controller.start_run(_request(tmp_path, api_key=secret))
    state = _wait_for(controller, lambda value: value["terminal"] and not value["active"])
    assert state["status"] == "failed"
    assert state["error_code"] == "runtime_error"
    rendered = json.dumps({"state": state, "events": controller.poll_events(500)})
    assert secret not in rendered
    assert "construction failed" not in rendered


def test_controller_shutdown_requests_stop_and_blocks_new_runs(tmp_path) -> None:
    engine = BlockingEngine()
    controller = DesktopController(runtime_factory=StaticFactory(engine))
    controller.start_run(_request(tmp_path))
    assert engine.started.wait(timeout=2)
    controller.shutdown(join_timeout=2)
    state = controller.get_state()["state"]
    assert state["closed"] is True
    assert state["active"] is False
    rejected = controller.start_run(_request(tmp_path))
    assert rejected["error_code"] == "runtime_error"
