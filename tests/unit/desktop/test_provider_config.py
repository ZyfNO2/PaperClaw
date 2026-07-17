from __future__ import annotations

from io import BytesIO
import json
import urllib.error

from paperclaw.desktop import app, provider_config


class FakeController:
    def __init__(self) -> None:
        self.last_request = None

    def start_run(self, request):
        self.last_request = request
        return {"ok": True, "status": "starting"}

    def cancel_run(self):
        return {"ok": True}

    def poll_events(self, limit):
        return {"ok": True, "items": [], "dropped_count": 0, "limit": limit}

    def get_state(self):
        return {"ok": True, "state": {"status": "idle"}}


class JsonResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


provider_config.install_provider_extension(app)


def _json_response(value) -> JsonResponse:
    return JsonResponse(json.dumps(value).encode("utf-8"))


def test_manual_provider_discovers_models_selects_one_and_injects_run_config(
    tmp_path,
    monkeypatch,
) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return _json_response(
            {
                "data": [
                    {"id": "model-a"},
                    {"id": "model-b"},
                    {"id": "model-a"},
                ]
            }
        )

    monkeypatch.setattr(provider_config, "_urlopen", fake_urlopen)
    controller = FakeController()
    api = app.DesktopAPI(controller)

    response = api.connect_provider(
        {
            "base_url": "https://provider.invalid/v1/",
            "api_key": "manual-secret",
            "provider": "openai-compatible",
        }
    )

    assert response["ok"] is True
    assert response["available_models"] == ["model-a", "model-b"]
    assert response["model"] == "model-a"
    assert captured == {
        "url": "https://provider.invalid/v1/models",
        "authorization": "Bearer manual-secret",
        "timeout": provider_config._CONNECT_TIMEOUT_SECONDS,
    }
    assert "manual-secret" not in repr(response)
    assert "api_key" not in response

    selected = api.select_provider_model("model-b")
    assert selected["ok"] is True
    assert selected["model"] == "model-b"

    started = api.start_run({"task": "hello", "workspace": str(tmp_path)})
    assert started["ok"] is True
    assert controller.last_request == {
        "task": "hello",
        "workspace": str(tmp_path),
        "base_url": "https://provider.invalid/v1",
        "api_key": "manual-secret",
        "model": "model-b",
        "provider": "openai-compatible",
    }

    defaults = api.get_defaults()
    assert defaults["provider_source"] == "manual"
    assert defaults["available_models"] == ["model-a", "model-b"]
    assert defaults["model"] == "model-b"
    assert "manual-secret" not in repr(defaults)


def test_manual_provider_errors_are_typed_and_never_echo_credentials(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"manual-secret"}'),
        )

    monkeypatch.setattr(provider_config, "_urlopen", fake_urlopen)
    api = app.DesktopAPI(FakeController())

    response = api.connect_provider(
        {
            "base_url": "https://provider.invalid/v1",
            "api_key": "manual-secret",
        }
    )

    assert response == {
        "ok": False,
        "error_code": "provider_authentication_error",
        "error_message": "Provider rejected the API key while listing models.",
    }
    assert "manual-secret" not in repr(response)


def test_manual_provider_can_be_cleared_back_to_environment(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_config,
        "_urlopen",
        lambda request, timeout: _json_response({"models": ["manual-model"]}),
    )
    monkeypatch.setenv("PAPERCLAW_API_KEY", "env-secret")
    monkeypatch.setenv("PAPERCLAW_BASE_URL", "https://env.invalid/v1")
    monkeypatch.setenv("PAPERCLAW_MODEL", "env-model")
    controller = FakeController()
    api = app.DesktopAPI(controller)

    assert api.connect_provider(
        {"base_url": "https://manual.invalid/v1", "api_key": "manual-secret"}
    )["ok"]
    assert api.clear_provider_config() == {"ok": True, "provider_source": "env"}

    response = api.start_run({"task": "hello", "workspace": str(tmp_path)})
    assert response["ok"] is True
    assert controller.last_request["api_key"] == "env-secret"
    assert controller.last_request["base_url"] == "https://env.invalid/v1"
    assert controller.last_request["model"] == "env-model"


def test_provider_extension_updates_browser_allowlists_and_is_idempotent() -> None:
    first_start_run = app.DesktopAPI.start_run
    provider_config.install_provider_extension(app)

    assert app.DesktopAPI.start_run is first_start_run
    assert app._BROWSER_API_ARITY["connect_provider"] == (1, 1)
    assert app._BROWSER_API_ARITY["select_provider_model"] == (1, 1)
    assert app._BROWSER_API_ARITY["clear_provider_config"] == (0, 0)
    assert app._BROWSER_ASSETS["/provider-config.js"][0] == "provider-config.js"
    assert app._BROWSER_ASSETS["/provider-config.css"][0] == "provider-config.css"
