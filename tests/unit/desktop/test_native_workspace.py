from __future__ import annotations

import importlib
from types import SimpleNamespace
import sys

from paperclaw.desktop import app
from paperclaw.desktop.native_workspace import install_native_workspace_extension


class FakeController:
    def start_run(self, request):
        return {"ok": True, "request": request}

    def cancel_run(self):
        return {"ok": True}

    def poll_events(self, limit):
        return {"ok": True, "items": [], "dropped_count": 0, "limit": limit}

    def get_state(self):
        return {"ok": True, "state": {"status": "idle"}}


class FakeWindow:
    def __init__(self, selected) -> None:
        self.selected = selected
        self.calls: list[str] = []

    def show(self) -> None:
        self.calls.append("show")

    def restore(self) -> None:
        self.calls.append("restore")

    def create_file_dialog(self, dialog_type):
        assert dialog_type == "folder"
        self.calls.append("dialog")
        return self.selected


class StaleWindow(FakeWindow):
    def create_file_dialog(self, dialog_type):
        assert dialog_type == "folder"
        self.calls.append("dialog")
        raise RuntimeError("native window is closed")


def _install() -> None:
    install_native_workspace_extension(app)


def test_bootstrap_installs_native_workspace_extension(monkeypatch) -> None:
    marker = "_paperclaw_native_workspace_extension"
    monkeypatch.delattr(app.DesktopAPI, marker, raising=False)
    from paperclaw.desktop import bootstrap

    importlib.reload(bootstrap)

    assert getattr(app.DesktopAPI, marker) is True


def test_native_workspace_extension_is_idempotent() -> None:
    _install()
    installed = app.DesktopAPI.select_workspace

    _install()

    assert app.DesktopAPI.select_workspace is installed


def test_bound_native_window_is_restored_before_dialog(tmp_path, monkeypatch) -> None:
    _install()
    window = FakeWindow((str(tmp_path),))
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(FileDialog=SimpleNamespace(FOLDER="folder"), windows=[]),
    )
    api = app.DesktopAPI(FakeController())
    api.bind_window(window)

    response = api.select_workspace()

    assert response == {"ok": True, "workspace": str(tmp_path.resolve())}
    assert window.calls == ["show", "restore", "dialog"]


def test_picker_recovers_window_from_pywebview_registry(tmp_path, monkeypatch) -> None:
    _install()
    window = FakeWindow((str(tmp_path),))
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(
            FileDialog=SimpleNamespace(FOLDER="folder"),
            active_window=lambda: None,
            windows=[window],
        ),
    )
    api = app.DesktopAPI(FakeController())

    response = api.select_workspace()

    assert response == {"ok": True, "workspace": str(tmp_path.resolve())}
    assert api._window is window
    assert window.calls == ["show", "restore", "dialog"]


def test_picker_prefers_active_native_window(tmp_path, monkeypatch) -> None:
    _install()
    active = FakeWindow((str(tmp_path),))
    fallback = FakeWindow(None)
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(
            FOLDER_DIALOG="folder",
            active_window=lambda: active,
            windows=[fallback],
        ),
    )
    api = app.DesktopAPI(FakeController())

    response = api.select_workspace()

    assert response["ok"] is True
    assert api._window is active
    assert active.calls == ["show", "restore", "dialog"]
    assert fallback.calls == []


def test_picker_retries_after_stale_bound_window(tmp_path, monkeypatch) -> None:
    _install()
    stale = StaleWindow(None)
    active = FakeWindow((str(tmp_path),))
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(
            FOLDER_DIALOG="folder",
            active_window=lambda: active,
            windows=[stale, active],
        ),
    )
    api = app.DesktopAPI(FakeController())
    api.bind_window(stale)

    response = api.select_workspace()

    assert response == {"ok": True, "workspace": str(tmp_path.resolve())}
    assert api._window is active
    assert stale.calls == ["show", "restore", "dialog"]
    assert active.calls == ["show", "restore", "dialog"]


def test_picker_cancel_is_non_destructive(monkeypatch) -> None:
    _install()
    window = FakeWindow(None)
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(FOLDER_DIALOG="folder", windows=[window]),
    )
    api = app.DesktopAPI(FakeController())

    assert api.select_workspace() == {"ok": True, "workspace": None}
    assert window.calls == ["show", "restore", "dialog"]


def test_picker_returns_typed_error_without_native_window(monkeypatch) -> None:
    _install()
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(
            FileDialog=SimpleNamespace(FOLDER="folder"),
            active_window=lambda: None,
            windows=[],
        ),
    )
    api = app.DesktopAPI(FakeController())

    response = api.select_workspace()

    assert response["ok"] is False
    assert response["error_code"] == "native_window_required"
    assert "active PaperClaw Desktop window" in response["error_message"]
