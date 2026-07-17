"""pywebview host and narrow JavaScript API for PaperClaw Desktop."""

from __future__ import annotations

import argparse
from importlib.resources import as_file, files
from importlib.util import find_spec
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from .contracts import DesktopPublicError
from .controller import DesktopController


class DesktopAPI:
    """Allow-listed methods exposed through ``window.pywebview.api``."""

    def __init__(self, controller: DesktopController) -> None:
        self._controller = controller
        self._window: Any | None = None

    def bind_window(self, window: Any) -> None:
        self._window = window

    def start_run(self, request: Mapping[str, Any]) -> dict[str, object]:
        return self._controller.start_run(request)

    def cancel_run(self) -> dict[str, object]:
        return self._controller.cancel_run()

    def poll_events(self, limit: int = 200) -> dict[str, object]:
        return self._controller.poll_events(limit)

    def get_state(self) -> dict[str, object]:
        return self._controller.get_state()

    def select_workspace(self) -> dict[str, object]:
        window = self._window
        if window is None:
            return DesktopPublicError(
                "runtime_error",
                "Desktop window is not ready.",
            ).to_public_dict()
        try:
            import webview

            dialog_type = _folder_dialog_type(webview)
            selected = window.create_file_dialog(dialog_type)
        except Exception:
            return DesktopPublicError(
                "runtime_error",
                "Workspace picker could not be opened.",
            ).to_public_dict()
        if not selected:
            return {"ok": True, "workspace": None}
        try:
            workspace = Path(selected[0]).expanduser().resolve(strict=True)
        except (IndexError, OSError, RuntimeError, TypeError, ValueError):
            return DesktopPublicError(
                "workspace_not_found",
                "Selected workspace could not be opened.",
            ).to_public_dict()
        if not workspace.is_dir():
            return DesktopPublicError(
                "workspace_not_found",
                "Selected workspace is not a directory.",
            ).to_public_dict()
        return {"ok": True, "workspace": str(workspace)}


def _folder_dialog_type(webview_module: Any) -> Any:
    """Support pywebview 5 constants and the pywebview 6 enum."""

    file_dialog = getattr(webview_module, "FileDialog", None)
    modern = getattr(file_dialog, "FOLDER", None) if file_dialog is not None else None
    legacy = getattr(webview_module, "FOLDER_DIALOG", None)
    dialog_type = modern if modern is not None else legacy
    if dialog_type is None:
        raise RuntimeError("pywebview folder dialog API is unavailable")
    return dialog_type


def pywebview_available() -> bool:
    try:
        return find_spec("webview") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def run_desktop(*, debug: bool = False) -> int:
    """Launch one native desktop window and block until it closes."""

    if not pywebview_available():
        raise DesktopPublicError(
            "gui_dependency_missing",
            "Desktop dependencies are missing. Install PaperClaw with the gui extra.",
        )

    try:
        import webview
    except ImportError as exc:
        raise DesktopPublicError(
            "gui_dependency_missing",
            "Desktop dependencies are missing. Install PaperClaw with the gui extra.",
        ) from exc

    controller = DesktopController()
    api = DesktopAPI(controller)
    index_resource = files("paperclaw.desktop").joinpath("static", "index.html")

    try:
        with as_file(index_resource) as index_path:
            try:
                webview.settings["ALLOW_FILE_URLS"] = True
            except (AttributeError, KeyError, TypeError):
                pass
            window = webview.create_window(
                "PaperClaw Desktop",
                url=index_path.resolve().as_uri(),
                js_api=api,
                width=1180,
                height=820,
                min_size=(620, 640),
                confirm_close=False,
                text_select=True,
            )
            api.bind_window(window)

            def on_closed(*_args: object) -> None:
                controller.shutdown()

            window.events.closed += on_closed
            webview.start(debug=bool(debug), private_mode=True)
    finally:
        controller.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch PaperClaw Desktop")
    parser.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        return run_desktop(debug=args.debug)
    except DesktopPublicError as exc:
        sys.stderr.write(json.dumps(exc.to_public_dict(), ensure_ascii=False) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
