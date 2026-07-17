from __future__ import annotations

import io
import json
import urllib.error

from paperclaw.desktop import app


class FakeController:
    def __init__(self) -> None:
        self.last_request = None

    def start_run(self, request):
        self.last_request = request
        return {"ok": True}

    def cancel_run(self):
        return {"ok": True}

    def poll_events(self, limit):
        return {"ok": True, "items": [], "limit": limit}

    def get_state(self):
        return {"ok": True, "state": {"status": "idle"}}


class FakeJSONResponse(io.BytesIO):
    def __init__(self, payload) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.headers = {}


def _http_error(request, status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        request.full_url,
        status,
        "provider error",
        {},
        io.BytesIO(b"provider error"),
    )


def test_manual_model_fallback_when_models_endpoint_is_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    for name in app._REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)

    def opener(request, timeout):
        del timeout
        raise _http_error(request, 404)

    controller = FakeController()
    api = app.DesktopAPI(controller, provider_urlopen=opener)

    response = api.connect_provider(
        {
            "base_url": "https://manual.invalid/v1",
            "api_key": "manual-secret",
            "provider": "openai-compatible",
            "model": "manual-only-model",
        }
    )

    assert response["ok"] is True
    assert response["selected_model"] == "manual-only-model"
    assert response["models"] == ["manual-only-model"]
    assert response["model_source"] == "manual"
    assert response["model_verified"] is False
    assert "without endpoint verification" in response["discovery_warning"]
    assert "manual-secret" not in repr(response)

    assert api.start_run({"task": "x", "workspace": str(tmp_path)})["ok"] is True
    assert controller.last_request["model"] == "manual-only-model"
    assert controller.last_request["api_key"] == "manual-secret"


def test_unlisted_model_requires_explicit_manual_opt_in() -> None:
    api = app.DesktopAPI(
        FakeController(),
        provider_urlopen=lambda request, timeout: FakeJSONResponse(
            {"data": [{"id": "listed-model"}]}
        ),
    )
    assert api.connect_provider(
        {
            "base_url": "https://manual.invalid/v1",
            "api_key": "secret",
            "provider": "openai-compatible",
        }
    )["ok"] is True

    rejected = api.select_provider_model("unlisted-model")
    assert rejected["ok"] is False
    assert rejected["error_code"] == "provider_configuration_error"

    accepted = api.select_provider_model("unlisted-model", True)
    assert accepted["ok"] is True
    assert accepted["model"] == "unlisted-model"
    assert accepted["model_source"] == "manual"
    assert accepted["model_verified"] is False
    assert accepted["models"][0] == "unlisted-model"
    assert api.get_defaults()["model"] == "unlisted-model"


def test_failed_reconnect_preserves_previous_active_configuration() -> None:
    attempts = 0

    def opener(request, timeout):
        nonlocal attempts
        del timeout
        attempts += 1
        if attempts == 1:
            return FakeJSONResponse({"data": [{"id": "stable-model"}]})
        raise _http_error(request, 401)

    api = app.DesktopAPI(FakeController(), provider_urlopen=opener)
    assert api.connect_provider(
        {
            "base_url": "https://stable.invalid/v1",
            "api_key": "stable-secret",
            "provider": "stable-provider",
        }
    )["ok"] is True

    failed = api.connect_provider(
        {
            "base_url": "https://broken.invalid/v1",
            "api_key": "broken-secret",
            "provider": "broken-provider",
        }
    )

    assert failed["ok"] is False
    assert failed["error_code"] == "provider_authentication_error"
    assert failed["active_configuration_preserved"] is True
    assert failed["active_provider"] == "stable-provider"
    assert failed["active_base_url"] == "https://stable.invalid/v1"
    assert failed["active_model"] == "stable-model"
    assert "Previous provider remains active" in failed["error_message"]
    assert "stable-secret" not in repr(failed)
    assert "broken-secret" not in repr(failed)
    assert api.get_defaults()["base_url"] == "https://stable.invalid/v1"


def test_clear_manual_provider_returns_to_environment_configuration(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAPERCLAW_API_KEY", "env-secret")
    monkeypatch.setenv("PAPERCLAW_BASE_URL", "https://env.invalid/v1")
    monkeypatch.setenv("PAPERCLAW_MODEL", "env-model")
    monkeypatch.setenv("PAPERCLAW_PROVIDER", "env-provider")

    controller = FakeController()
    api = app.DesktopAPI(
        controller,
        provider_urlopen=lambda request, timeout: FakeJSONResponse(
            {"data": [{"id": "manual-model"}]}
        ),
    )
    assert api.connect_provider(
        {
            "base_url": "https://manual.invalid/v1",
            "api_key": "manual-secret",
            "provider": "manual-provider",
        }
    )["ok"] is True

    cleared = api.clear_manual_provider()

    assert cleared["ok"] is True
    assert cleared["manual_provider_cleared"] is True
    assert cleared["provider_source"] == "env"
    assert cleared["provider"] == "env-provider"
    assert cleared["model"] == "env-model"
    assert "manual-secret" not in repr(cleared)

    assert api.start_run({"task": "x", "workspace": str(tmp_path)})["ok"] is True
    assert controller.last_request["api_key"] == "env-secret"
    assert controller.last_request["base_url"] == "https://env.invalid/v1"
    assert controller.last_request["model"] == "env-model"


def test_failed_manual_connection_reports_environment_as_still_active(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAPERCLAW_API_KEY", "env-secret")
    monkeypatch.setenv("PAPERCLAW_BASE_URL", "https://env.invalid/v1")
    monkeypatch.setenv("PAPERCLAW_MODEL", "env-model")
    monkeypatch.setenv("PAPERCLAW_PROVIDER", "env-provider")

    def opener(request, timeout):
        del timeout
        raise _http_error(request, 401)

    api = app.DesktopAPI(FakeController(), provider_urlopen=opener)
    failed = api.connect_provider(
        {
            "base_url": "https://broken.invalid/v1",
            "api_key": "broken-secret",
            "provider": "broken-provider",
        }
    )

    assert failed["ok"] is False
    assert failed["active_configuration_preserved"] is True
    assert failed["active_provider_source"] == "env"
    assert failed["active_provider"] == "env-provider"
    assert failed["active_model"] == "env-model"
    assert "Previous environment configuration remains active" in failed["error_message"]
    assert "env-secret" not in repr(failed)
    assert "broken-secret" not in repr(failed)
