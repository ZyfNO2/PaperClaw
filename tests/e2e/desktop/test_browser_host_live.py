from __future__ import annotations

from copy import deepcopy
from threading import RLock

import pytest
from playwright.sync_api import Browser, Page, expect

from paperclaw.desktop import app
import paperclaw.desktop.bootstrap  # noqa: F401  # install production extensions/assets


class DeterministicController:
    def __init__(self) -> None:
        self._lock = RLock()
        self._items: list[dict[str, object]] = []
        self._state: dict[str, object] = {
            "run_id": None,
            "status": "idle",
            "model_calls": 0,
            "tool_calls": 0,
            "last_sequence": 0,
            "terminal": False,
            "verification_status": None,
            "verification_summary": None,
            "final_result": None,
            "error_code": None,
            "error_message": None,
        }

    def start_run(self, request):
        with self._lock:
            if self._state["status"] in {"starting", "running", "stopping"}:
                return {
                    "ok": False,
                    "error_code": "run_already_active",
                    "error_message": "A run is already active.",
                }
            self._state.update(run_id="browser-run", status="starting", terminal=False)
            self._items.extend(
                [
                    {"kind": "snapshot", "snapshot": deepcopy(self._state)},
                    {
                        "kind": "event",
                        "event": {
                            "sequence": 1,
                            "event_type": "run.started",
                            "label": "run.started",
                        },
                    },
                    {
                        "kind": "event",
                        "event": {
                            "sequence": 2,
                            "event_type": "model.completed",
                            "label": "model.completed · call=1",
                        },
                    },
                    {
                        "kind": "event",
                        "event": {
                            "sequence": 3,
                            "event_type": "tool.completed",
                            "label": "tool.completed · tool=read",
                        },
                    },
                ]
            )
            self._state.update(
                status="running", model_calls=1, tool_calls=1, last_sequence=3
            )
            self._items.append({"kind": "snapshot", "snapshot": deepcopy(self._state)})
            if request["task"] != "keep running":
                self._state.update(
                    status="completed",
                    terminal=True,
                    verification_status="passed",
                    verification_summary="deterministic checks passed",
                    final_result="Deterministic browser run completed.",
                )
                self._items.append(
                    {"kind": "snapshot", "snapshot": deepcopy(self._state)}
                )
            return {"ok": True, "accepted": True, "status": "starting"}

    def cancel_run(self):
        with self._lock:
            if self._state["status"] != "running":
                return {
                    "ok": False,
                    "error_code": "run_not_active",
                    "error_message": "There is no active run to cancel.",
                }
            self._state.update(status="stopping")
            self._items.append({"kind": "snapshot", "snapshot": deepcopy(self._state)})
            self._state.update(status="cancelled", terminal=True)
            self._items.append({"kind": "snapshot", "snapshot": deepcopy(self._state)})
            return {"ok": True, "accepted": True, "status": "stopping"}

    def poll_events(self, limit):
        with self._lock:
            selected = self._items[:limit]
            del self._items[:limit]
            return {"ok": True, "items": selected, "dropped_count": 0}

    def get_state(self):
        with self._lock:
            return {"ok": True, "state": deepcopy(self._state)}


@pytest.fixture
def browser_host(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAPERCLAW_API_KEY", "not-returned-to-browser")
    monkeypatch.setenv("PAPERCLAW_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("PAPERCLAW_MODEL", "deterministic-model")
    api = app.DesktopAPI(DeterministicController())
    host = app._BrowserHost(api)
    host.start()
    try:
        yield host
    finally:
        host.stop()


def _open(page: Page, host: app._BrowserHost) -> None:
    page.goto(host.url_for_theme("dark"), wait_until="domcontentloaded")
    expect(page.locator("#workspace-path")).to_have_text(str(host._api.get_defaults()["workspace"]))


def test_real_loopback_browser_host_completes_run_without_console_errors(
    browser: Browser, browser_host: app._BrowserHost
) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        _open(page, browser_host)
        page.locator("#task").fill("complete through loopback")
        page.locator("#send-button").click()
        expect(page.locator("#run-status")).to_have_text("COMPLETED", timeout=5000)
        expect(page.locator("#model-calls")).to_have_text("1")
        expect(page.locator("#tool-calls")).to_have_text("1")
        expect(page.locator("#timeline .event-row")).to_have_count(3)
        expect(page.locator("#mission-log")).to_contain_text(
            "Deterministic browser run completed."
        )
        assert errors == []
    finally:
        page.close()


def test_two_browser_tabs_observe_same_run_and_cancel_independently(
    browser: Browser, browser_host: app._BrowserHost
) -> None:
    first = browser.new_page()
    second = browser.new_page()
    try:
        _open(first, browser_host)
        _open(second, browser_host)
        first.locator("#task").fill("keep running")
        first.locator("#run-button").click()
        expect(first.locator("#run-status")).to_have_text("RUNNING", timeout=5000)
        expect(second.locator("#run-status")).to_have_text("RUNNING", timeout=5000)
        expect(first.locator("#timeline .event-row")).to_have_count(3)
        expect(second.locator("#timeline .event-row")).to_have_count(3)

        second.locator("#cancel-button").click()
        expect(first.locator("#run-status")).to_have_text("CANCELLED", timeout=5000)
        expect(second.locator("#run-status")).to_have_text("CANCELLED", timeout=5000)
    finally:
        first.close()
        second.close()
