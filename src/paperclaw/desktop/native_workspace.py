"""Native-window workspace selection for the PaperClaw Desktop bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_EXTENSION_MARKER = "_paperclaw_native_workspace_extension"


def install_native_workspace_extension(app_module: Any) -> None:
    """Install the native-only workspace picker on ``DesktopAPI`` once."""

    api_type = app_module.DesktopAPI
    if getattr(api_type, _EXTENSION_MARKER, False):
        return

    def select_workspace(self: Any) -> dict[str, object]:
        try:
            import webview
        except ImportError:
            return _native_window_required(app_module)

        window = _resolve_native_window(webview, getattr(self, "_window", None))
        if window is None:
            return _native_window_required(app_module)

        self._window = window
        _prepare_native_window(window)
        try:
            dialog_type = app_module._folder_dialog_type(webview)
            selected = window.create_file_dialog(dialog_type)
        except Exception:
            return app_module.DesktopPublicError(
                "runtime_error",
                "Workspace picker could not be opened.",
            ).to_public_dict()

        if not selected:
            return {"ok": True, "workspace": None}
        try:
            workspace = Path(selected[0]).expanduser().resolve(strict=True)
        except (IndexError, OSError, RuntimeError, TypeError, ValueError):
            return app_module.DesktopPublicError(
                "workspace_not_found",
                "Selected workspace could not be opened.",
            ).to_public_dict()
        if not workspace.is_dir():
            return app_module.DesktopPublicError(
                "workspace_not_found",
                "Selected workspace is not a directory.",
            ).to_public_dict()
        return {"ok": True, "workspace": str(workspace)}

    api_type.select_workspace = select_workspace
    setattr(api_type, _EXTENSION_MARKER, True)


def _native_window_required(app_module: Any) -> dict[str, object]:
    return app_module.DesktopPublicError(
        "native_window_required",
        "Workspace selection requires an active PaperClaw Desktop window.",
    ).to_public_dict()


def _resolve_native_window(webview_module: Any, bound_window: Any | None) -> Any | None:
    """Resolve a live pywebview window for native-only operations."""

    if _supports_folder_dialog(bound_window):
        return bound_window

    active_window = getattr(webview_module, "active_window", None)
    if callable(active_window):
        try:
            candidate = active_window()
        except Exception:
            candidate = None
        if _supports_folder_dialog(candidate):
            return candidate

    windows = getattr(webview_module, "windows", ())
    try:
        candidates = list(windows)
    except TypeError:
        candidates = []
    for candidate in candidates:
        if _supports_folder_dialog(candidate):
            return candidate
    return None


def _supports_folder_dialog(window: Any | None) -> bool:
    return window is not None and callable(getattr(window, "create_file_dialog", None))


def _prepare_native_window(window: Any) -> None:
    """Bring a hidden or minimized native host forward before the dialog opens."""

    for operation_name in ("show", "restore"):
        operation = getattr(window, operation_name, None)
        if not callable(operation):
            continue
        try:
            operation()
        except Exception:
            # Dialog creation is authoritative; activation remains best-effort.
            continue
