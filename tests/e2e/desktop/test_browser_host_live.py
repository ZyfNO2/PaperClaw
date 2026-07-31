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
        self._dropped = 0
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
            if request["task"] == "backend error":
                return {
                    "ok": False,
                    "error_code": "provider_configuration_error",
                    "error_message": "Safe deterministic provider error.",
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
            if request["task"] == "report dropped events":
                self._dropped = 3
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
            return {"ok": True, "items": selected, "dropped_count": self._dropped}

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
    expect(page.locator("#workspace-path")).not_to_have_text("Waiting for desktop bridge")


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


def test_browser_public_error_recovers_controls_and_allows_retry(
    browser: Browser, browser_host: app._BrowserHost
) -> None:
    page = browser.new_page()
    try:
        _open(page, browser_host)
        page.locator("#task").fill("backend error")
        page.locator("#run-button").click()
        expect(page.locator("#public-error")).to_contain_text(
            "provider_configuration_error"
        )
        expect(page.locator("#run-button")).to_be_enabled()

        page.locator("#task").fill("retry succeeds")
        page.locator("#run-button").click()
        expect(page.locator("#run-status")).to_have_text("COMPLETED", timeout=5000)
    finally:
        page.close()


def test_browser_surfaces_dropped_events_and_native_only_picker_error(
    browser: Browser, browser_host: app._BrowserHost
) -> None:
    page = browser.new_page()
    try:
        _open(page, browser_host)
        page.locator("#task").fill("report dropped events")
        page.locator("#run-button").click()
        expect(page.locator("#event-meta")).to_have_text("3 dropped", timeout=5000)

        page.locator('#sidebar-nav [data-nav="papers"]').click()
        page.get_by_role("button", name="IMPORT PAPER").click()
        expect(page.locator("#papers-root [role=alert]").last).to_contain_text(
            "native_window_required"
        )
    finally:
        page.close()


def test_browser_reconnects_after_invalid_poll_response_and_exposes_safe_debug(
    browser: Browser, browser_host: app._BrowserHost
) -> None:
    page = browser.new_page()
    failures = 0

    def disrupt(route) -> None:
        nonlocal failures
        if failures == 0:
            failures += 1
            route.fulfill(status=200, content_type="text/plain", body="not-json")
        else:
            route.continue_()

    page.route("**/api/poll_events", disrupt)
    try:
        origin, fragment = browser_host.url_for_theme("dark").split("/#", 1)
        page.goto(f"{origin}/?debug=1#{fragment}", wait_until="domcontentloaded")
        expect(page.locator("#public-error")).to_contain_text("invalid_response")
        expect(page.locator("#frontend-diagnostics")).to_be_visible()
        expect(page.locator("#frontend-diagnostics")).to_contain_text(
            '"polling_interval_ms": 3000'
        )
        expect(page.locator("#frontend-diagnostics")).to_contain_text('"connected": true', timeout=5000)
        diagnostic = page.locator("#frontend-diagnostics").text_content() or ""
        assert "not-returned-to-browser" not in diagnostic
        assert "X-PaperClaw-Token" not in diagnostic
    finally:
        page.close()


def test_hidden_document_uses_reduced_polling_frequency(
    browser: Browser, browser_host: app._BrowserHost
) -> None:
    page = browser.new_page()
    try:
        origin, fragment = browser_host.url_for_theme("dark").split("/#", 1)
        page.goto(f"{origin}/?debug=1#{fragment}", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
              Object.defineProperty(document, 'hidden', {value: true, configurable: true});
              document.dispatchEvent(new Event('visibilitychange'));
            }"""
        )
        expect(page.locator("#frontend-diagnostics")).to_contain_text(
            '"polling_interval_ms": 4000'
        )
    finally:
        page.close()


def test_initialization_is_idempotent_and_version_comes_from_backend(
    browser: Browser, browser_host: app._BrowserHost
) -> None:
    original = browser_host._api.get_defaults
    calls = 0

    def counted_defaults():
        nonlocal calls
        calls += 1
        return original()

    browser_host._api.get_defaults = counted_defaults
    page = browser.new_page()
    try:
        _open(page, browser_host)
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        expect(page.locator("#brand-version")).to_have_text("v0.38.0 · workbench")
        assert calls == 1
    finally:
        page.close()


@pytest.mark.parametrize(
    ("width", "height"),
    [(1440, 900), (1280, 720), (1024, 768), (768, 1024), (420, 760)],
)
def test_key_viewports_have_no_horizontal_document_overflow(
    browser: Browser, browser_host: app._BrowserHost, width: int, height: int
) -> None:
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        _open(page, browser_host)
        dimensions = page.evaluate(
            "() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})"
        )
        assert dimensions["scroll"] <= dimensions["client"]
        expect(page.locator("#task")).to_be_attached()
        expect(page.locator("#sidebar-toggle")).to_be_visible()
    finally:
        page.close()
