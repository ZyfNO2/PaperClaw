"""Manual OpenAI-compatible provider discovery for the desktop UI.

The extension is installed before the desktop host starts. It keeps credentials
in Python memory only, exposes a small allow-listed API to pywebview / the
protected loopback browser bridge, and injects the selected provider into new
runs without mutating process environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import json
import platform
import socket
from typing import Any, Mapping
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .contracts import DesktopPublicError

_CONNECT_TIMEOUT_SECONDS = 15.0
_PROVIDER_STATE_ATTRIBUTE = "_paperclaw_manual_provider_state"
_INSTALLED_ATTRIBUTE = "_paperclaw_provider_extension_installed"
_PROVIDER_FIELDS = frozenset({"base_url", "api_key", "model", "provider"})
_DISCOVERY_FALLBACK_CODES = frozenset(
    {"provider_models_unavailable", "provider_response_error"}
)

# Kept module-level so focused tests can replace the network boundary.
_urlopen = urllib.request.urlopen


@dataclass(frozen=True)
class _ManualProviderState:
    base_url: str
    api_key: str = field(repr=False)
    provider: str = "openai-compatible"
    models: tuple[str, ...] = ()
    selected_model: str = ""
    model_verified: bool = True
    discovery_warning: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        output: dict[str, object] = {
            "provider_source": "manual",
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.selected_model,
            "available_models": list(self.models),
            "configured": True,
            "missing": [],
            "credential_configured": True,
            "model_source": "discovered" if self.model_verified else "manual",
            "model_verified": self.model_verified,
        }
        if self.discovery_warning:
            output["discovery_warning"] = self.discovery_warning
        return output


def install_provider_extension(app_module: Any) -> None:
    """Patch the desktop host once, before any ``DesktopAPI`` instance exists."""

    if getattr(app_module, _INSTALLED_ATTRIBUTE, False):
        return
    desktop_api = app_module.DesktopAPI
    original_start_run = desktop_api.start_run
    original_get_defaults = desktop_api.get_defaults

    def connect_provider(self: Any, value: Mapping[str, Any]) -> dict[str, object]:
        previous = _get_state(self)
        try:
            base_url, api_key, provider, manual_model = _validate_connection_request(
                value
            )
            warning: str | None = None
            try:
                discovered = _discover_models(base_url, api_key)
            except DesktopPublicError as exc:
                if manual_model and exc.code in _DISCOVERY_FALLBACK_CODES:
                    discovered = (manual_model,)
                    warning = (
                        "Model discovery was unavailable. The manually entered "
                        "model will be used without endpoint verification."
                    )
                else:
                    return _provider_error_response(
                        exc,
                        previous,
                        original_get_defaults(self),
                    )

            if manual_model:
                verified = manual_model in discovered and warning is None
                models = discovered
                if manual_model not in models:
                    models = (manual_model, *models)
                selected_model = manual_model
                if not verified and warning is None:
                    warning = (
                        "The selected model was entered manually and was not "
                        "listed by the provider."
                    )
            else:
                verified = True
                models = discovered
                selected_model = models[0]

            state = _ManualProviderState(
                base_url=base_url,
                api_key=api_key,
                provider=provider,
                models=models,
                selected_model=selected_model,
                model_verified=verified,
                discovery_warning=warning,
            )
            setattr(self, _PROVIDER_STATE_ATTRIBUTE, state)
            return {"ok": True, **state.to_public_dict()}
        except DesktopPublicError as exc:
            return _provider_error_response(
                exc,
                previous,
                original_get_defaults(self),
            )

    def select_provider_model(
        self: Any,
        model: str,
        allow_unlisted: bool = False,
    ) -> dict[str, object]:
        state = _get_state(self)
        if state is None:
            return DesktopPublicError(
                "provider_configuration_error",
                "Connect to a provider before selecting a model.",
            ).to_public_dict()
        if not isinstance(allow_unlisted, bool):
            return DesktopPublicError(
                "validation_error",
                "allow_unlisted must be a boolean.",
            ).to_public_dict()
        normalized = str(model).strip() if isinstance(model, str) else ""
        if not normalized or len(normalized) > 256:
            return DesktopPublicError(
                "provider_configuration_error",
                "Selected model must be non-empty text up to 256 characters.",
            ).to_public_dict()
        listed = normalized in state.models
        if not listed and not allow_unlisted:
            return DesktopPublicError(
                "provider_configuration_error",
                "Selected model is not available from the connected provider.",
            ).to_public_dict()
        models = state.models if listed else (normalized, *state.models)
        updated = _ManualProviderState(
            base_url=state.base_url,
            api_key=state.api_key,
            provider=state.provider,
            models=models,
            selected_model=normalized,
            model_verified=listed,
            discovery_warning=(
                None
                if listed
                else "The selected model is manually entered and unverified."
            ),
        )
        setattr(self, _PROVIDER_STATE_ATTRIBUTE, updated)
        return {"ok": True, **updated.to_public_dict()}

    def clear_provider_config(self: Any) -> dict[str, object]:
        if hasattr(self, _PROVIDER_STATE_ATTRIBUTE):
            delattr(self, _PROVIDER_STATE_ATTRIBUTE)
        return {"ok": True, "provider_source": "env"}

    def get_defaults(self: Any) -> dict[str, object]:
        defaults = original_get_defaults(self)
        state = _get_state(self)
        if state is None or not defaults.get("ok"):
            return defaults
        merged = dict(defaults)
        merged.update(state.to_public_dict())
        return merged

    def start_run(self: Any, request: Mapping[str, Any]) -> dict[str, object]:
        state = _get_state(self)
        if state is None or not isinstance(request, Mapping):
            return original_start_run(self, request)

        hydrated = dict(request)
        explicit = {
            name for name in _PROVIDER_FIELDS if hydrated.get(name) not in (None, "")
        }
        # Never combine a partially explicit endpoint/model with an unrelated
        # in-memory credential. Explicit provider fields are validated as one unit
        # by the existing controller/runtime path.
        if explicit:
            return original_start_run(self, hydrated)
        hydrated.update(
            {
                "base_url": state.base_url,
                "api_key": state.api_key,
                "model": state.selected_model,
                "provider": state.provider,
            }
        )
        return original_start_run(self, hydrated)

    desktop_api.connect_provider = connect_provider
    desktop_api.select_provider_model = select_provider_model
    desktop_api.clear_provider_config = clear_provider_config
    desktop_api.get_defaults = get_defaults
    desktop_api.start_run = start_run

    app_module._BROWSER_API_ARITY.update(
        {
            "connect_provider": (1, 1),
            "select_provider_model": (1, 2),
            "clear_provider_config": (0, 0),
        }
    )
    app_module._BROWSER_ASSETS.update(
        {
            "/provider-config.js": (
                "provider-config.js",
                "text/javascript; charset=utf-8",
            ),
            "/provider-config.css": (
                "provider-config.css",
                "text/css; charset=utf-8",
            ),
        }
    )
    setattr(app_module, _INSTALLED_ATTRIBUTE, True)


def _get_state(api: Any) -> _ManualProviderState | None:
    value = getattr(api, _PROVIDER_STATE_ATTRIBUTE, None)
    return value if isinstance(value, _ManualProviderState) else None


def _provider_error_response(
    exc: DesktopPublicError,
    previous: _ManualProviderState | None,
    environment_defaults: Mapping[str, Any],
) -> dict[str, object]:
    response = exc.to_public_dict()
    if previous is not None:
        response.update(
            {
                "active_configuration_preserved": True,
                "active_provider_source": "manual",
                "active_provider": previous.provider,
                "active_base_url": previous.base_url,
                "active_model": previous.selected_model,
                "error_message": (
                    f"{response['error_message']} Previous provider remains active."
                ),
            }
        )
    elif environment_defaults.get("ok") and environment_defaults.get("configured"):
        response.update(
            {
                "active_configuration_preserved": True,
                "active_provider_source": "env",
                "active_provider": environment_defaults.get("provider"),
                "active_base_url": environment_defaults.get("base_url"),
                "active_model": environment_defaults.get("model"),
                "error_message": (
                    f"{response['error_message']} Previous environment "
                    "configuration remains active."
                ),
            }
        )
    else:
        response["active_configuration_preserved"] = False
    return response


def _validate_connection_request(
    value: Mapping[str, Any],
) -> tuple[str, str, str, str | None]:
    if not isinstance(value, Mapping):
        raise DesktopPublicError(
            "validation_error",
            "Provider connection request must be an object.",
        )
    allowed = {"base_url", "api_key", "provider", "model"}
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise DesktopPublicError(
            "validation_error",
            f"Unknown provider fields: {', '.join(unknown[:10])}.",
        )

    base_url = _required_text(value.get("base_url"), "Base URL", 2_000).rstrip("/")
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

    api_key = _required_text(value.get("api_key"), "API key", 20_000)
    provider = _required_text(
        value.get("provider", "openai-compatible"),
        "Provider",
        128,
    )
    raw_model = value.get("model")
    manual_model: str | None = None
    if raw_model not in (None, ""):
        manual_model = _required_text(raw_model, "Model", 256)
    return base_url, api_key, provider, manual_model


def _required_text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise DesktopPublicError("validation_error", f"{label} must be text.")
    normalized = value.strip()
    if not normalized:
        raise DesktopPublicError("validation_error", f"{label} must not be empty.")
    if len(normalized) > limit:
        raise DesktopPublicError("validation_error", f"{label} is too long.")
    return normalized


def _discover_models(base_url: str, api_key: str) -> tuple[str, ...]:
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
        with _urlopen(request, timeout=_CONNECT_TIMEOUT_SECONDS) as response:
            try:
                payload = json.load(response)
            except (TypeError, ValueError) as exc:
                raise DesktopPublicError(
                    "provider_response_error",
                    "Provider model list returned invalid JSON.",
                ) from exc
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            message = "Provider rejected the API key while listing models."
            code = "provider_authentication_error"
        elif exc.code in {400, 404, 405}:
            message = "Provider does not expose a compatible /models endpoint."
            code = "provider_models_unavailable"
        else:
            message = f"Provider model list failed with HTTP {exc.code}."
            code = "provider_connection_error"
        raise DesktopPublicError(code, message) from exc
    except (
        urllib.error.URLError,
        http.client.RemoteDisconnected,
        ConnectionError,
        TimeoutError,
        socket.timeout,
    ) as exc:
        raise DesktopPublicError(
            "provider_network_error",
            "Provider model list timed out or could not be reached.",
        ) from exc

    models = _extract_models(payload)
    if not models:
        raise DesktopPublicError(
            "provider_response_error",
            "Provider returned no selectable models.",
        )
    return models


def _extract_models(payload: Any) -> tuple[str, ...]:
    values: Any = payload
    if isinstance(payload, Mapping):
        values = payload.get("data")
        if not isinstance(values, list):
            values = payload.get("models")
    if not isinstance(values, list):
        return ()

    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        candidate: Any = item
        if isinstance(item, Mapping):
            candidate = item.get("id") or item.get("name")
        if not isinstance(candidate, str):
            continue
        normalized = candidate.strip()
        if not normalized or len(normalized) > 256 or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)
