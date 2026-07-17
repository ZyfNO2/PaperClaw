"""pywebview host and narrow JavaScript API for PaperClaw Desktop."""

from __future__ import annotations

import argparse
import http.client
from importlib.resources import as_file, files
from importlib.util import find_spec
import json
import os
from pathlib import Path
import platform
import socket
import sys
from threading import RLock
from typing import Any, Mapping
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .contracts import DesktopPublicError
from .controller import DesktopController
from .diagnostics import record_exception

_PROVIDER_FIELDS = frozenset({"base_url", "api_key", "model", "provider"})
_REQUIRED_ENV = (
    "PAPERCLAW_API_KEY",
    "PAPERCLAW_BASE_URL",
    "PAPERCLAW_MODEL",
)
_MAX_DISCOVERED_MODELS = 1_000


class DesktopAPI:
    """Allow-listed methods exposed through ``window.pywebview.api``."""

    def __init__(
        self,
        controller: DesktopController,
        *,
        provider_urlopen: Any | None = None,
        provider_timeout: float = 20.0,
    ) -> None:
        self._controller = controller
        self._window: Any | None = None
        self._provider_urlopen = provider_urlopen or urllib.request.urlopen
        self._provider_timeout = max(1.0, float(provider_timeout))
        self._provider_lock = RLock()
        self._manual_provider: dict[str, str] | None = None
        self._available_models: tuple[str, ...] = ()

    def bind_window(self, window: Any) -> None:
        self._window = window

    def start_run(self, request: Mapping[str, Any]) -> dict[str, object]:
        try:
            hydrated = self._hydrate_provider(request)
        except DesktopPublicError as exc:
            return exc.to_public_dict()
        return self._controller.start_run(hydrated)

    def cancel_run(self) -> dict[str, object]:
        return self._controller.cancel_run()

    def poll_events(self, limit: int = 200) -> dict[str, object]:
        return self._controller.poll_events(limit)

    def get_state(self) -> dict[str, object]:
        return self._controller.get_state()

    def get_defaults(self) -> dict[str, object]:
        """Return non-secret desktop defaults for the initial UI projection."""

        workspace = Path.cwd().expanduser().resolve()
        with self._provider_lock:
            manual_provider = dict(self._manual_provider) if self._manual_provider else None
            models = list(self._available_models)
        if manual_provider is not None:
            return {
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
        }

    def connect_provider(self, request: Mapping[str, Any]) -> dict[str, object]:
        """Validate one manual provider and discover its available models.

        The credential is retained only in this Python process. The response sent
        to JavaScript contains connection metadata and model IDs, never the key.
        """

        try:
            provider_config = _validate_provider_connection_request(request)
            models = _discover_provider_models(
                provider_config,
                urlopen=self._provider_urlopen,
                timeout=self._provider_timeout,
            )
        except DesktopPublicError as exc:
            return exc.to_public_dict()

        selected_model = models[0]
        with self._provider_lock:
            self._manual_provider = {
                **provider_config,
                "model": selected_model,
            }
            self._available_models = tuple(models)
        return {
            "ok": True,
            "provider_source": "manual",
            "provider": provider_config["provider"],
            "base_url": provider_config["base_url"],
            "models": list(models),
            "selected_model": selected_model,
            "configured": True,
        }

    def select_provider_model(self, model: str) -> dict[str, object]:
        """Select a discovered model for subsequent runs."""

        try:
            selected = _required_provider_text(model, "Model", limit=256)
        except DesktopPublicError as exc:
            return exc.to_public_dict()
        with self._provider_lock:
            if self._manual_provider is None:
                return DesktopPublicError(
                    "provider_configuration_error",
                    "Connect a provider before selecting a model.",
                ).to_public_dict()
            if selected not in self._available_models:
                return DesktopPublicError(
                    "provider_configuration_error",
                    "Selected model is not available from the connected provider.",
                ).to_public_dict()
            self._manual_provider = {**self._manual_provider, "model": selected}
            provider = self._manual_provider["provider"]
            base_url = self._manual_provider["base_url"]
        return {
            "ok": True,
            "provider_source": "manual",
            "provider": provider,
            "base_url": base_url,
            "model": selected,
        }

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
    allowed_fields = {"base_url", "api_key", "provider"}
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
    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "provider": provider,
    }


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
        if exc.code == 404:
            raise DesktopPublicError(
                "provider_configuration_error",
                "Provider model-list endpoint was not found at Base URL /models.",
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
    except Exception as exc:
        record_exception("desktop_host_error", exc)
        public_error = DesktopPublicError(
            "runtime_error",
            "Desktop host failed. See the local desktop diagnostic log.",
        )
        sys.stderr.write(json.dumps(public_error.to_public_dict(), ensure_ascii=False) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
