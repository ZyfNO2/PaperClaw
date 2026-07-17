from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

from paperclaw import entrypoint
from paperclaw.desktop import app
from paperclaw.desktop.contracts import DesktopPublicError


class FakeController:
    def start_run(self, request):
        return {"ok": True, "request_size": len(request)}

    def cancel_run(self):
        return {"ok": True, "accepted": True}

    def poll_events(self, limit):
        return {"ok": True, "items": [], "limit": limit}

    def get_state(self):
        return {"ok": True, "state": {"status": "idle"}}


class FakeWindow:
    def __init__(self, result) -> None:
        self.result = result

    def create_file_dialog(self, dialog_type):
        assert dialog_type == "folder"
        return self.result


def test_desktop_api_exposes_only_narrow_controller_operations(tmp_path, monkeypatch) -> None:
    api = app.DesktopAPI(FakeController())
    assert api.start_run({"task": "x"}) == {"ok": True, "request_size": 1}
    assert api.cancel_run() == {"ok": True, "accepted": True}
    assert api.poll_events(7) == {"ok": True, "items": [], "limit": 7}
    assert api.get_state()["state"]["status"] == "idle"

    fake_webview = SimpleNamespace(FOLDER_DIALOG="folder")
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    api.bind_window(FakeWindow((str(tmp_path),)))
    assert api.select_workspace() == {"ok": True, "workspace": str(tmp_path.resolve())}


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


def test_console_entrypoint_routes_gui_and_preserves_legacy_commands(monkeypatch) -> None:
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
