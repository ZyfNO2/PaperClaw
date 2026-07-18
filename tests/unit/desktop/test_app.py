from __future__ import annotations

import json
from types import SimpleNamespace
import sys
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import pytest

from paperclaw import entrypoint
from paperclaw.desktop import app
from paperclaw.desktop.contracts import DesktopPublicError


class FakeController:
    def __init__(self) -> None:
        self.last_request = None

    def start_run(self, request):
        self.last_request = request
        return {"ok": True, "request_size": len(request)}

    def cancel_run(self):
        return {"ok": True, "accepted": True}

    def poll_events(self, limit):
        return {"ok": True, "items": [], "limit": limit, "dropped_count": 0}

    def get_state(self):
        return {"ok": True, "state": {"status": "idle"}}


class QueueController(FakeController):
    def __init__(self, items) -> None:
        super().__init__()
        self.items = list(items)

    def poll_events(self, limit):
        selected = self.items[:limit]
        del self.items[:limit]
        return {"ok": True, "items": selected, "dropped_count": 0}


class FakeWindow:
    def __init__(self, result) -> None:
        self.result = result

    def create_file_dialog(self, dialog_type):
        assert dialog_type == "folder"
        return self.result


def _set_provider_env(monkeypatch) -> None:
    monkeypatch.setenv("PAPERCLAW_API_KEY", "secret-value")
    monkeypatch.setenv("PAPERCLAW_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("PAPERCLAW_MODEL", "test-model")
    monkeypatch.setenv("PAPERCLAW_PROVIDER", "test-provider")


def test_desktop_api_hydrates_default_run_from_environment(
    tmp_path, monkeypatch
) -> None:
    _set_provider_env(monkeypatch)
    controller = FakeController()
    api = app.DesktopAPI(controller)

    response = api.start_run({"task": "x", "workspace": str(tmp_path)})

    assert response["ok"] is True
    assert controller.last_request == {
        "task": "x",
        "workspace": str(tmp_path),
        "api_key": "secret-value",
        "base_url": "https://example.invalid/v1",
        "model": "test-model",
        "provider": "test-provider",
    }


def test_environment_defaults_never_expose_api_key(tmp_path, monkeypatch) -> None:
    _set_provider_env(monkeypatch)
    monkeypatch.setenv("PAPERCLAW_DESKTOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    api = app.DesktopAPI(FakeController())

    defaults = api.get_defaults()

    assert defaults == {
        "ok": True,
        "workspace": str(tmp_path.resolve()),
        "provider_source": "env",
        "provider": "test-provider",
        "base_url": "https://example.invalid/v1",
        "model": "test-model",
        "configured": True,
        "missing": [],
        "theme": "neo-brutalist",
    }
    assert "secret-value" not in repr(defaults)
    assert "api_key" not in defaults


def test_theme_preference_is_validated_and_persisted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPERCLAW_DESKTOP_CONFIG_DIR", str(tmp_path))
    api = app.DesktopAPI(FakeController())

    assert api.set_theme("terminal-dark") == {"ok": True, "theme": "terminal-dark"}
    assert api.get_defaults()["theme"] == "terminal-dark"
    invalid = api.set_theme("unknown-theme")
    assert invalid["ok"] is False
    assert invalid["error_code"] == "validation_error"
    assert (
        json.loads((tmp_path / "desktop-preferences.json").read_text())["theme"]
        == "terminal-dark"
    )


def test_missing_environment_is_a_typed_public_error(tmp_path, monkeypatch) -> None:
    for name in app._REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    controller = FakeController()
    api = app.DesktopAPI(controller)

    response = api.start_run({"task": "x", "workspace": str(tmp_path)})

    assert response["ok"] is False
    assert response["error_code"] == "provider_configuration_error"
    assert "PAPERCLAW_API_KEY" in response["error_message"]
    assert controller.last_request is None


def test_workspace_dotenv_is_loaded_without_overriding_process_env(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("PAPERCLAW_MODEL", "process-model")
    monkeypatch.delenv("PAPERCLAW_API_KEY", raising=False)
    monkeypatch.delenv("PAPERCLAW_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "PAPERCLAW_API_KEY=file-secret\n"
        "PAPERCLAW_BASE_URL=https://file.invalid/v1\n"
        "PAPERCLAW_MODEL=file-model\n",
        encoding="utf-8",
    )
    controller = FakeController()
    api = app.DesktopAPI(controller)

    response = api.start_run({"task": "x", "workspace": str(tmp_path)})

    assert response["ok"] is True
    assert controller.last_request["api_key"] == "file-secret"
    assert controller.last_request["base_url"] == "https://file.invalid/v1"
    assert controller.last_request["model"] == "process-model"


def test_explicit_provider_configuration_remains_supported(
    tmp_path, monkeypatch
) -> None:
    for name in app._REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    controller = FakeController()
    api = app.DesktopAPI(controller)
    request = {
        "task": "x",
        "workspace": str(tmp_path),
        "api_key": "explicit-secret",
        "base_url": "https://explicit.invalid/v1",
        "model": "explicit-model",
        "provider": "explicit-provider",
    }

    response = api.start_run(request)

    assert response["ok"] is True
    assert controller.last_request == request


def test_desktop_api_exposes_controller_operations_and_workspace_picker(
    tmp_path, monkeypatch
) -> None:
    _set_provider_env(monkeypatch)
    api = app.DesktopAPI(FakeController())
    assert api.cancel_run() == {"ok": True, "accepted": True}
    assert api.poll_events(7) == {"ok": True, "items": [], "dropped_count": 0}
    assert api.get_state()["state"]["status"] == "idle"

    fake_webview = SimpleNamespace(FOLDER_DIALOG="folder")
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    api.bind_window(FakeWindow((str(tmp_path),)))
    assert api.select_workspace() == {"ok": True, "workspace": str(tmp_path.resolve())}


def test_poll_events_fans_out_to_desktop_and_browser_clients() -> None:
    items = [
        {"kind": "event", "event": {"sequence": 1, "event_type": "run.started"}},
        {"kind": "snapshot", "snapshot": {"status": "running"}},
    ]
    api = app.DesktopAPI(QueueController(items))

    assert api.poll_events(10, "desktop")["items"] == items
    assert api.poll_events(10, "browser-1")["items"] == items
    assert api.poll_events(10, "desktop")["items"] == []
    assert api.poll_events(10, "browser-1")["items"] == []


def test_browser_host_serves_assets_and_requires_fragment_token(
    tmp_path, monkeypatch
) -> None:
    _set_provider_env(monkeypatch)
    monkeypatch.setenv("PAPERCLAW_DESKTOP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    opened_urls = []
    monkeypatch.setattr(
        app.webbrowser,
        "open_new_tab",
        lambda value: opened_urls.append(value) or True,
    )
    api = app.DesktopAPI(FakeController())

    try:
        response = api.open_in_browser("paper-light")
        assert response["ok"] is True
        assert response["origin"].startswith("http://127.0.0.1:")
        opened = urlsplit(opened_urls[0])
        fragment = parse_qs(opened.fragment)
        assert fragment["theme"] == ["paper-light"]
        token = fragment["token"][0]

        with urlopen(response["origin"] + "/", timeout=3) as page:
            assert page.status == 200
            assert b"PaperClaw Console" in page.read()

        unauthorized = Request(
            response["origin"] + "/api/get_defaults",
            data=b'{"args":[]}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(unauthorized, timeout=3)
        assert denied.value.code == 403

        authorized = Request(
            response["origin"] + "/api/get_defaults",
            data=b'{"args":[]}',
            headers={
                "Content-Type": "application/json",
                "X-PaperClaw-Token": token,
            },
            method="POST",
        )
        with urlopen(authorized, timeout=3) as api_response:
            payload = json.loads(api_response.read())
        assert payload["ok"] is True
        assert payload["configured"] is True
        assert "api_key" not in payload
        assert "secret-value" not in repr(payload)
    finally:
        api.shutdown_browser()


def test_workspace_picker_cancel_is_not_an_error(monkeypatch) -> None:
    api = app.DesktopAPI(FakeController())
    fake_webview = SimpleNamespace(FOLDER_DIALOG="folder")
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    api.bind_window(FakeWindow(None))
    assert api.select_workspace() == {"ok": True, "workspace": None}


def test_run_desktop_fails_cleanly_without_optional_dependency(monkeypatch) -> None:
    monkeypatch.setattr(app, "pywebview_available", lambda: False)
    with pytest.raises(DesktopPublicError) as raised:
        app.run_desktop()
    assert raised.value.code == "gui_dependency_missing"
    assert "pywebview" not in str(raised.value).lower()


def test_console_entrypoint_routes_gui_and_preserves_legacy_commands(
    monkeypatch,
) -> None:
    observed = []

    def desktop_main(argv):
        observed.append(("gui", argv))
        return 7

    def legacy_main(argv):
        observed.append(("legacy", argv))
        return 9

    monkeypatch.setattr(app, "main", desktop_main)
    import paperclaw.cli

    monkeypatch.setattr(paperclaw.cli, "main", legacy_main)
    assert entrypoint.main(["gui"]) == 7
    assert entrypoint.main(["gui", "--debug"]) == 7
    assert entrypoint.main(["agent", "task"]) == 9
    assert entrypoint.main(["legacy positional task"]) == 9
    assert observed == [
        ("gui", []),
        ("gui", ["--debug"]),
        ("legacy", ["agent", "task"]),
        ("legacy", ["legacy positional task"]),
    ]


def test_desktop_app_module_does_not_import_pywebview_at_import_time() -> None:
    source = app.__loader__.get_source(app.__name__)
    top_level_prefix = source.split("class DesktopAPI", 1)[0]
    assert "import webview" not in top_level_prefix
