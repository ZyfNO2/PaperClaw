from __future__ import annotations

import os

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
        return {"ok": True, "items": [], "dropped_count": 0}

    def get_state(self):
        return {"ok": True, "state": {"status": "idle"}}


def _write_provider_env(path, suffix):
    path.mkdir()
    (path / ".env").write_text(
        f"PAPERCLAW_API_KEY=secret-{suffix}\n"
        f"PAPERCLAW_BASE_URL=https://{suffix}.invalid/v1\n"
        f"PAPERCLAW_MODEL=model-{suffix}\n",
        encoding="utf-8",
    )


def test_switching_workspaces_does_not_reuse_previous_dotenv_credentials(
    tmp_path, monkeypatch
):
    for name in (*app._REQUIRED_ENV, "PAPERCLAW_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_provider_env(first, "first")
    _write_provider_env(second, "second")
    controller = FakeController()
    api = app.DesktopAPI(controller)

    assert api.start_run({"task": "one", "workspace": str(first)})["ok"]
    assert controller.last_request["api_key"] == "secret-first"
    assert api.start_run({"task": "two", "workspace": str(second)})["ok"]
    assert controller.last_request["api_key"] == "secret-second"
    assert controller.last_request["base_url"] == "https://second.invalid/v1"
    assert controller.last_request["model"] == "model-second"
    for name in app._REQUIRED_ENV:
        assert os.getenv(name) is None


def test_process_environment_still_overrides_workspace_dotenv(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    _write_provider_env(workspace, "file")
    monkeypatch.setenv("PAPERCLAW_MODEL", "process-model")
    monkeypatch.delenv("PAPERCLAW_API_KEY", raising=False)
    monkeypatch.delenv("PAPERCLAW_BASE_URL", raising=False)

    values = app._resolve_provider_environment(workspace)

    assert values["PAPERCLAW_API_KEY"] == "secret-file"
    assert values["PAPERCLAW_BASE_URL"] == "https://file.invalid/v1"
    assert values["PAPERCLAW_MODEL"] == "process-model"
