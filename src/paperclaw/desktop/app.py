"""pywebview host and narrow JavaScript API for PaperClaw Desktop."""

from __future__ import annotations

import argparse
<<<<<<< HEAD
from collections import OrderedDict, deque
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
=======
import http.client
>>>>>>> f189121
from importlib.resources import as_file, files
from importlib.util import find_spec
import json
import os
from pathlib import Path
<<<<<<< HEAD
import secrets
import sys
from threading import RLock, Thread
from typing import Any, Mapping
from urllib.parse import quote, urlsplit
import webbrowser
=======
import platform
import socket
import sys
from threading import RLock
from typing import Any, Mapping
import urllib.error
import urllib.request
from urllib.parse import urlsplit
>>>>>>> f189121

from .contracts import DesktopPublicError
from .controller import DesktopController
from .diagnostics import record_exception

_PROVIDER_FIELDS = frozenset({"base_url", "api_key", "model", "provider"})
_REQUIRED_ENV = (
    "PAPERCLAW_API_KEY",
    "PAPERCLAW_BASE_URL",
    "PAPERCLAW_MODEL",
)
<<<<<<< HEAD
<<<<<<< HEAD
=======
_BROWSER_THEMES = frozenset(
    {
        "neo-brutalist",
        "soft-minimal",
        "terminal-dark",
        "clean-mono",
        "paper-light",
    }
)
_BROWSER_ASSETS = {
    "": ("index.html", "text/html; charset=utf-8"),
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
_BROWSER_API_ARITY: dict[str, tuple[int, int]] = {
    "get_defaults": (0, 0),
    "get_state": (0, 0),
    "start_run": (1, 1),
    "cancel_run": (0, 0),
    "poll_events": (1, 2),
    "select_workspace": (0, 0),
    "set_theme": (1, 1),
}
_BROWSER_MAX_REQUEST_BYTES = 1_000_000
_EVENT_HISTORY_LIMIT = 2_048
_CLIENT_CURSOR_LIMIT = 32
>>>>>>> edf37eb
=======
_MAX_DISCOVERED_MODELS = 1_000
_MODEL_DISCOVERY_FALLBACK_CODES = frozenset(
    {"provider_configuration_error", "provider_invalid_response"}
)
>>>>>>> f189121


class DesktopAPI:
    """Allow-listed methods exposed through ``window.pywebview.api`` and loopback HTTP."""

    def __init__(
        self,
        controller: DesktopController,
        *,
        provider_urlopen: Any | None = None,
        provider_timeout: float = 20.0,
    ) -> None:
        self._controller = controller
        self._window: Any | None = None
<<<<<<< HEAD
        self._browser_host: _BrowserHost | None = None
        self._browser_lock = RLock()
        self._poll_lock = RLock()
        self._event_history: deque[tuple[int, dict[str, object]]] = deque(
            maxlen=_EVENT_HISTORY_LIMIT
        )
        self._event_serial = 0
        self._client_cursors: OrderedDict[str, int] = OrderedDict()
=======
        self._provider_urlopen = provider_urlopen or urllib.request.urlopen
        self._provider_timeout = max(1.0, float(provider_timeout))
        self._provider_lock = RLock()
        self._manual_provider: dict[str, str] | None = None
        self._available_models: tuple[str, ...] = ()
        self._manual_model_selected = False
>>>>>>> f189121

    def bind_window(self, window: Any) -> None:
        self._window = window

    def start_run(self, request: Mapping[str, Any]) -> dict[str, object]:
        try:
            hydrated = self._hydrate_provider(request)
        except DesktopPublicError as exc:
            return exc.to_public_dict()
<<<<<<< HEAD
=======
        self._reset_event_fanout()
>>>>>>> edf37eb
        return self._controller.start_run(hydrated)

    def cancel_run(self) -> dict[str, object]:
        return self._controller.cancel_run()

    def poll_events(
        self,
        limit: int = 200,
        client_id: str = "desktop",
    ) -> dict[str, object]:
        """Fan out the controller's destructive queue to independent UI clients."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 500
        ):
            return DesktopPublicError(
                "validation_error",
                "limit must be an integer in [1, 500]",
            ).to_public_dict()
        normalized_client = _normalize_client_id(client_id)
        if normalized_client is None:
            return DesktopPublicError(
                "validation_error",
                "client_id must be a short non-empty string.",
            ).to_public_dict()

        with self._poll_lock:
            drained = self._controller.poll_events(500)
            if not drained.get("ok"):
                return drained
            for item in drained.get("items", []):
                if not isinstance(item, Mapping):
                    continue
                self._event_serial += 1
                self._event_history.append((self._event_serial, deepcopy(dict(item))))

            oldest_serial = (
                self._event_history[0][0]
                if self._event_history
                else self._event_serial + 1
            )
            cursor = self._client_cursors.get(normalized_client, oldest_serial - 1)
            mirror_dropped = max(0, oldest_serial - cursor - 1)
            if mirror_dropped:
                cursor = oldest_serial - 1

            selected: list[dict[str, object]] = []
            next_cursor = cursor
            for serial, item in self._event_history:
                if serial <= cursor:
                    continue
                selected.append(deepcopy(item))
                next_cursor = serial
                if len(selected) >= limit:
                    break

            self._remember_client_cursor(normalized_client, next_cursor)
            dropped_count = (
                _non_negative_int(drained.get("dropped_count")) + mirror_dropped
            )
            return {
                "ok": True,
                "items": selected,
                "dropped_count": dropped_count,
            }

    def get_state(self) -> dict[str, object]:
        return self._controller.get_state()

    def get_defaults(self) -> dict[str, object]:
        """Return non-secret desktop defaults for the initial UI projection."""

        workspace = Path.cwd().expanduser().resolve()
        with self._provider_lock:
            manual_provider = dict(self._manual_provider) if self._manual_provider else None
            models = list(self._available_models)
            manual_model_selected = self._manual_model_selected
        if manual_provider is not None:
            response: dict[str, object] = {
                "ok": True,
                "workspace": str(workspace),
                "provider_source": "manual",
                "provider": manual_provider["provider"],
                "base_url": manual_provider["base_url"],
                "model": manual_provider["model"],
                "models": models,
                "configured": True,
                "missing": [],
            }
            if manual_model_selected:
                response["model_source"] = "manual"
                response["model_verified"] = False
            return response

        _load_dotenv(workspace / ".env")
        missing = [name for name in _REQUIRED_ENV if not os.getenv(name)]
        model = os.getenv("PAPERCLAW_MODEL") or None
        return {
            "ok": True,
            "workspace": str(workspace),
            "provider_source": "env",
            "provider": os.getenv("PAPERCLAW_PROVIDER", "openai-compatible"),
            "base_url": os.getenv("PAPERCLAW_BASE_URL") or None,
            "model": model,
            "models": [model] if model else [],
            "configured": not missing,
            "missing": missing,
<<<<<<< HEAD
        }

<<<<<<< HEAD
=======
            "theme": _load_theme_preference(),
        }

    def set_theme(self, theme: str) -> dict[str, object]:
        if theme not in _BROWSER_THEMES:
            return DesktopPublicError(
                "validation_error",
                "Unknown desktop theme.",
            ).to_public_dict()
        try:
            _save_theme_preference(theme)
        except OSError:
            return DesktopPublicError(
                "runtime_error",
                "Theme preference could not be saved.",
            ).to_public_dict()
        return {"ok": True, "theme": theme}

>>>>>>> edf37eb
=======
    def connect_provider(self, request: Mapping[str, Any]) -> dict[str, object]:
        """Validate a manual provider and load models when the endpoint supports it.

        A supplied manual model lets OpenAI-compatible providers work even when
        ``GET /models`` is unavailable. The credential remains only in this Python
        process and is never returned to JavaScript.
        """

        try:
            provider_config = _validate_provider_connection_request(request)
        except DesktopPublicError as exc:
            return self._provider_error_response(exc)

        manual_model = provider_config.pop("model", "")
        discovery_warning = ""
        manual_model_selected = False
        try:
            models = _discover_provider_models(
                provider_config,
                urlopen=self._provider_urlopen,
                timeout=self._provider_timeout,
            )
        except DesktopPublicError as exc:
            if manual_model and exc.code in _MODEL_DISCOVERY_FALLBACK_CODES:
                models = [manual_model]
                discovery_warning = (
                    "Model discovery was unavailable. The manually entered model "
                    "will be used without endpoint verification."
                )
                manual_model_selected = True
            else:
                return self._provider_error_response(exc)

        if manual_model:
            selected_model = manual_model
            manual_model_selected = manual_model not in models or manual_model_selected
            if manual_model not in models:
                models.insert(0, manual_model)
        else:
            selected_model = models[0]

        with self._provider_lock:
            self._manual_provider = {
                **provider_config,
                "model": selected_model,
            }
            self._available_models = tuple(models)
            self._manual_model_selected = manual_model_selected

        response: dict[str, object] = {
            "ok": True,
            "provider_source": "manual",
            "provider": provider_config["provider"],
            "base_url": provider_config["base_url"],
            "models": list(models),
            "selected_model": selected_model,
            "configured": True,
        }
        if manual_model_selected:
            response.update(
                {
                    "model_source": "manual",
                    "model_verified": False,
                    "discovery_warning": discovery_warning
                    or "The selected model was entered manually and was not listed by the provider.",
                }
            )
        return response

    def select_provider_model(
        self,
        model: str,
        allow_unlisted: bool = False,
    ) -> dict[str, object]:
        """Select a discovered model, or explicitly opt into an unlisted one."""

        try:
            selected = _required_provider_text(model, "Model", limit=256)
            if not isinstance(allow_unlisted, bool):
                raise DesktopPublicError(
                    "validation_error",
                    "allow_unlisted must be a boolean.",
                )
        except DesktopPublicError as exc:
            return exc.to_public_dict()

        with self._provider_lock:
            if self._manual_provider is None:
                return DesktopPublicError(
                    "provider_configuration_error",
                    "Connect a provider before selecting a model.",
                ).to_public_dict()
            is_listed = selected in self._available_models
            if not is_listed and not allow_unlisted:
                return DesktopPublicError(
                    "provider_configuration_error",
                    "Selected model is not available from the connected provider.",
                ).to_public_dict()
            if not is_listed:
                self._available_models = (selected, *self._available_models)
            self._manual_provider = {**self._manual_provider, "model": selected}
            self._manual_model_selected = not is_listed and allow_unlisted
            provider = self._manual_provider["provider"]
            base_url = self._manual_provider["base_url"]
            models = list(self._available_models)

        response: dict[str, object] = {
            "ok": True,
            "provider_source": "manual",
            "provider": provider,
            "base_url": base_url,
            "model": selected,
        }
        if allow_unlisted:
            response.update(
                {
                    "models": models,
                    "selected_model": selected,
                    "configured": True,
                    "model_source": "manual" if not is_listed else "discovered",
                    "model_verified": bool(is_listed),
                }
            )
        return response

    def clear_manual_provider(self) -> dict[str, object]:
        """Drop the in-memory credential and return to ENV/.env resolution."""

        with self._provider_lock:
            cleared = self._manual_provider is not None
            if self._manual_provider is not None:
                self._manual_provider["api_key"] = ""
            self._manual_provider = None
            self._available_models = ()
            self._manual_model_selected = False
        response = self.get_defaults()
        response["manual_provider_cleared"] = cleared
        return response

>>>>>>> f189121
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

<<<<<<< HEAD
    def open_in_browser(self, theme: str = "neo-brutalist") -> dict[str, object]:
        """Open a token-protected loopback mirror in the system browser."""

        normalized_theme = theme if theme in _BROWSER_THEMES else "neo-brutalist"
        try:
            with self._browser_lock:
                if self._browser_host is None:
                    self._browser_host = _BrowserHost(self)
                host = self._browser_host
                host.start()
                browser_url = host.url_for_theme(normalized_theme)
            opened = bool(webbrowser.open_new_tab(browser_url))
        except Exception as exc:
            record_exception("desktop_browser_open_error", exc)
            return DesktopPublicError(
                "runtime_error",
                "The browser interface could not be opened.",
            ).to_public_dict()
        if not opened:
            return DesktopPublicError(
                "runtime_error",
                "No system browser accepted the PaperClaw interface URL.",
            ).to_public_dict()
        return {
            "ok": True,
            "opened": True,
            "mode": "browser",
            "origin": host.origin,
        }

    def shutdown_browser(self) -> None:
        with self._browser_lock:
            host = self._browser_host
            self._browser_host = None
        if host is not None:
            host.stop()

    def _reset_event_fanout(self) -> None:
        with self._poll_lock:
            self._event_history.clear()
            self._client_cursors.clear()
            self._event_serial = 0

    def _remember_client_cursor(self, client_id: str, cursor: int) -> None:
        self._client_cursors.pop(client_id, None)
        self._client_cursors[client_id] = cursor
        while len(self._client_cursors) > _CLIENT_CURSOR_LIMIT:
            self._client_cursors.popitem(last=False)


class _BrowserHost:
    """Serve static assets and the allow-listed API on an ephemeral loopback port."""

    def __init__(self, api: DesktopAPI) -> None:
        self._api = api
        self._token = secrets.token_urlsafe(32)
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._lock = RLock()

    @property
    def origin(self) -> str:
        server = self._server
        if server is None:
            raise RuntimeError("Browser host is not running")
        host, port = server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        with self._lock:
            if self._server is not None:
                return
            handler = self._handler_type()
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server.daemon_threads = True
            thread = Thread(
                target=server.serve_forever,
                name="paperclaw-browser-host",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            try:
                thread.start()
            except RuntimeError:
                self._server = None
                self._thread = None
                server.server_close()
                raise

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def url_for_theme(self, theme: str) -> str:
        fragment = f"token={quote(self._token)}&theme={quote(theme)}"
        return f"{self.origin}/#{fragment}"

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        api = self._api
        token = self._token

        class BrowserRequestHandler(BaseHTTPRequestHandler):
            server_version = "PaperClawLoopback/0.11"
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if path == "/favicon.ico":
                    self._send_bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
                    return
                asset = _BROWSER_ASSETS.get(path)
                if asset is None:
                    self._send_json(
                        HTTPStatus.NOT_FOUND,
                        DesktopPublicError(
                            "not_found",
                            "Browser asset was not found.",
                        ).to_public_dict(),
                    )
                    return
                filename, content_type = asset
                try:
                    data = (
                        files("paperclaw.desktop")
                        .joinpath("static", filename)
                        .read_bytes()
                    )
                except OSError:
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        DesktopPublicError(
                            "runtime_error",
                            "Browser asset could not be loaded.",
                        ).to_public_dict(),
                    )
                    return
                self._send_bytes(HTTPStatus.OK, data, content_type)

            def do_POST(self) -> None:  # noqa: N802
                if not secrets.compare_digest(
                    self.headers.get("X-PaperClaw-Token", ""),
                    token,
                ):
                    self._send_json(
                        HTTPStatus.FORBIDDEN,
                        DesktopPublicError(
                            "permission_denied",
                            "Browser API access was denied.",
                        ).to_public_dict(),
                    )
                    return

                path = urlsplit(self.path).path
                method_name = (
                    path.removeprefix("/api/") if path.startswith("/api/") else ""
                )
                arity = _BROWSER_API_ARITY.get(method_name)
                if arity is None:
                    self._send_json(
                        HTTPStatus.NOT_FOUND,
                        DesktopPublicError(
                            "not_found",
                            "Browser API method was not found.",
                        ).to_public_dict(),
                    )
                    return
                payload = self._read_json_body()
                if payload is None:
                    return
                args = payload.get("args", []) if isinstance(payload, Mapping) else []
                if not isinstance(args, list) or not arity[0] <= len(args) <= arity[1]:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        DesktopPublicError(
                            "validation_error",
                            "Browser API arguments are invalid.",
                        ).to_public_dict(),
                    )
                    return
                try:
                    target = getattr(api, method_name)
                    response = target(*args)
                except Exception as exc:
                    record_exception("desktop_browser_api_error", exc)
                    response = DesktopPublicError(
                        "runtime_error",
                        "Browser API operation failed.",
                    ).to_public_dict()
                self._send_json(HTTPStatus.OK, response)

            def _read_json_body(self) -> Mapping[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if length < 0 or length > _BROWSER_MAX_REQUEST_BYTES:
                    self._send_json(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        DesktopPublicError(
                            "validation_error",
                            "Browser API request is too large.",
                        ).to_public_dict(),
                    )
                    return None
                try:
                    raw = self.rfile.read(length)
                    decoded = json.loads(raw.decode("utf-8") or "{}")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        DesktopPublicError(
                            "validation_error",
                            "Browser API request must be valid JSON.",
                        ).to_public_dict(),
                    )
                    return None
                if not isinstance(decoded, Mapping):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        DesktopPublicError(
                            "validation_error",
                            "Browser API request must be an object.",
                        ).to_public_dict(),
                    )
                    return None
                return decoded

            def _send_json(self, status: HTTPStatus, value: Mapping[str, Any]) -> None:
                data = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self._send_bytes(status, data, "application/json; charset=utf-8")

            def _send_bytes(
                self,
                status: HTTPStatus,
                data: bytes,
                content_type: str,
            ) -> None:
                self.send_response(status.value)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Connection", "close")
                self.end_headers()
                if data:
                    self.wfile.write(data)
                self.close_connection = True

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return BrowserRequestHandler


def _hydrate_environment_provider(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise DesktopPublicError("validation_error", "Run request must be an object.")
    hydrated = dict(request)
    explicit_fields = {
        name for name in _PROVIDER_FIELDS if hydrated.get(name) not in (None, "")
    }
    if explicit_fields:
        return hydrated

    workspace_value = hydrated.get("workspace")
    if isinstance(workspace_value, str) and workspace_value.strip():
        workspace = Path(workspace_value).expanduser()
        _load_dotenv(workspace / ".env")
    _load_dotenv(Path.cwd() / ".env")

    values = {name: os.getenv(name) for name in _REQUIRED_ENV}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise DesktopPublicError(
            "provider_configuration_error",
            f"Missing environment variables: {', '.join(missing)}.",
        )
    hydrated.update(
        {
            "api_key": values["PAPERCLAW_API_KEY"],
            "base_url": values["PAPERCLAW_BASE_URL"],
            "model": values["PAPERCLAW_MODEL"],
            "provider": os.getenv("PAPERCLAW_PROVIDER", "openai-compatible"),
        }
    )
    return hydrated


def _load_dotenv(dotenv_path: Path) -> None:
    """Load a local .env without replacing explicit process environment values."""

    try:
        if not dotenv_path.is_file():
            return
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key:
            os.environ.setdefault(normalized_key, value.strip())


def _preference_path() -> Path:
    override = os.getenv("PAPERCLAW_DESKTOP_CONFIG_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".paperclaw"
    return base / "desktop-preferences.json"


def _load_theme_preference() -> str:
    path = _preference_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "neo-brutalist"
    if not isinstance(payload, Mapping):
        return "neo-brutalist"
    theme = payload.get("theme")
    return (
        theme
        if isinstance(theme, str) and theme in _BROWSER_THEMES
        else "neo-brutalist"
    )


def _save_theme_preference(theme: str) -> None:
    path = _preference_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"theme": theme}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
=======
    def _provider_error_response(self, exc: DesktopPublicError) -> dict[str, object]:
        response = exc.to_public_dict()
        with self._provider_lock:
            active = dict(self._manual_provider) if self._manual_provider else None
        if active is not None:
            response.update(
                {
                    "active_configuration_preserved": True,
                    "active_provider_source": "manual",
                    "active_provider": active["provider"],
                    "active_base_url": active["base_url"],
                    "active_model": active["model"],
                    "error_message": (
                        f"{response['error_message']} Previous provider remains active."
                    ),
                }
            )
            return response

        defaults = self.get_defaults()
        env_active = bool(defaults.get("configured"))
        response["active_configuration_preserved"] = env_active
        if env_active:
            response.update(
                {
                    "active_provider_source": "env",
                    "active_provider": defaults.get("provider"),
                    "active_base_url": defaults.get("base_url"),
                    "active_model": defaults.get("model"),
                    "error_message": (
                        f"{response['error_message']} Previous environment configuration "
                        "remains active."
                    ),
                }
            )
        return response

    def _hydrate_provider(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise DesktopPublicError("validation_error", "Run request must be an object.")
        hydrated = dict(request)
        explicit_fields = {
            name for name in _PROVIDER_FIELDS if hydrated.get(name) not in (None, "")
        }
        if explicit_fields:
            return hydrated
        with self._provider_lock:
            manual_provider = dict(self._manual_provider) if self._manual_provider else None
        if manual_provider is not None:
            hydrated.update(manual_provider)
            return hydrated
        return _hydrate_environment_provider(hydrated)
>>>>>>> f189121


def _hydrate_environment_provider(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise DesktopPublicError("validation_error", "Run request must be an object.")
    hydrated = dict(request)
    explicit_fields = {name for name in _PROVIDER_FIELDS if hydrated.get(name) not in (None, "")}
    if explicit_fields:
        return hydrated

    workspace_value = hydrated.get("workspace")
    if isinstance(workspace_value, str) and workspace_value.strip():
        workspace = Path(workspace_value).expanduser()
        _load_dotenv(workspace / ".env")
    _load_dotenv(Path.cwd() / ".env")

    values = {name: os.getenv(name) for name in _REQUIRED_ENV}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise DesktopPublicError(
            "provider_configuration_error",
            f"Missing environment variables: {', '.join(missing)}.",
        )
    hydrated.update(
        {
            "api_key": values["PAPERCLAW_API_KEY"],
            "base_url": values["PAPERCLAW_BASE_URL"],
            "model": values["PAPERCLAW_MODEL"],
            "provider": os.getenv("PAPERCLAW_PROVIDER", "openai-compatible"),
        }
    )
    return hydrated


def _validate_provider_connection_request(request: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(request, Mapping):
        raise DesktopPublicError(
            "validation_error",
            "Provider connection request must be an object.",
        )
    allowed_fields = {"base_url", "api_key", "provider", "model"}
    unknown = sorted(str(key) for key in request if key not in allowed_fields)
    if unknown:
        raise DesktopPublicError(
            "validation_error",
            f"Unknown provider fields: {', '.join(unknown[:10])}.",
        )
    base_url = _required_provider_text(request.get("base_url"), "Base URL", limit=2_000)
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DesktopPublicError(
            "provider_configuration_error",
            "Base URL must be an absolute HTTP or HTTPS URL.",
        )
    if parsed.username or parsed.password:
        raise DesktopPublicError(
            "provider_configuration_error",
            "Base URL must not contain embedded credentials.",
        )
    api_key = _required_provider_text(request.get("api_key"), "API key", limit=20_000)
    provider = _required_provider_text(
        request.get("provider", "openai-compatible"),
        "Provider",
        limit=128,
    )
    result = {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "provider": provider,
    }
    manual_model = request.get("model")
    if manual_model not in (None, ""):
        result["model"] = _required_provider_text(manual_model, "Model", limit=256)
    return result


def _discover_provider_models(
    provider_config: Mapping[str, str],
    *,
    urlopen: Any,
    timeout: float,
) -> list[str]:
    base_url = provider_config["base_url"]
    api_key = provider_config["api_key"]
    request = urllib.request.Request(
        f"{base_url}/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": (
                f"PaperClaw/0.0.1 ({platform.system()} {platform.release()})"
            ),
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise DesktopPublicError(
                "provider_authentication_error",
                "Provider rejected the supplied API key or permission.",
            ) from exc
        if exc.code in {400, 404, 405}:
            raise DesktopPublicError(
                "provider_configuration_error",
                "Provider model-list endpoint is unavailable at Base URL /models.",
            ) from exc
        raise DesktopPublicError(
            "provider_connection_error",
            f"Provider model discovery failed with HTTP {exc.code}.",
        ) from exc
    except (
        urllib.error.URLError,
        http.client.RemoteDisconnected,
        ConnectionError,
        TimeoutError,
        socket.timeout,
    ) as exc:
        raise DesktopPublicError(
            "provider_network_error",
            "Provider could not be reached or the connection timed out.",
        ) from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DesktopPublicError(
            "provider_invalid_response",
            "Provider returned invalid JSON for the model list.",
        ) from exc

    models = _extract_model_ids(payload)
    if not models:
        raise DesktopPublicError(
            "provider_invalid_response",
            "Provider returned no selectable model IDs.",
        )
    return models


def _extract_model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        return []

    models: list[str] = []
    seen: set[str] = set()
    for item in raw_models:
        candidate: Any = item
        if isinstance(item, Mapping):
            candidate = item.get("id") or item.get("model") or item.get("name")
        if not isinstance(candidate, str):
            continue
        model_id = candidate.strip()
        if not model_id or len(model_id) > 256 or model_id in seen:
            continue
        seen.add(model_id)
        models.append(model_id)
        if len(models) >= _MAX_DISCOVERED_MODELS:
            break
    return models


def _required_provider_text(value: Any, label: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise DesktopPublicError("validation_error", f"{label} must be text.")
    normalized = value.strip()
    if not normalized:
        raise DesktopPublicError("validation_error", f"{label} must not be empty.")
    if len(normalized) > limit:
        raise DesktopPublicError("validation_error", f"{label} is too long.")
    return normalized


def _load_dotenv(dotenv_path: Path) -> None:
    """Load a local .env without replacing explicit process environment values."""

    try:
        if not dotenv_path.is_file():
            return
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key:
            os.environ.setdefault(normalized_key, value.strip())


def _folder_dialog_type(webview_module: Any) -> Any:
    """Support pywebview 5 constants and the pywebview 6 enum."""

    file_dialog = getattr(webview_module, "FileDialog", None)
    modern = getattr(file_dialog, "FOLDER", None) if file_dialog is not None else None
    legacy = getattr(webview_module, "FOLDER_DIALOG", None)
    dialog_type = modern if modern is not None else legacy
    if dialog_type is None:
        raise RuntimeError("pywebview folder dialog API is unavailable")
    return dialog_type


def _normalize_client_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 80:
        return None
    return normalized


def _non_negative_int(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, normalized)


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
                width=1440,
                height=900,
                min_size=(720, 640),
                confirm_close=False,
                text_select=True,
            )
            api.bind_window(window)

            def on_closed(*_args: object) -> None:
                api.shutdown_browser()
                controller.shutdown()

            window.events.closed += on_closed
            webview.start(debug=bool(debug), private_mode=True)
    finally:
        api.shutdown_browser()
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
    except Exception as exc:
        record_exception("desktop_host_error", exc)
        public_error = DesktopPublicError(
            "runtime_error",
            "Desktop host failed. See the local desktop diagnostic log.",
        )
        sys.stderr.write(
            json.dumps(public_error.to_public_dict(), ensure_ascii=False) + "\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
