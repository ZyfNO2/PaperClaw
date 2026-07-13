import json
import os
import sys
import urllib.request
from pathlib import Path

from paperclaw.cli import _build_parser, load_dotenv, main
from paperclaw.models.adapters.openai_compat import OpenAICompatibleModel


def test_load_dotenv_sets_missing_values_only(tmp_path: Path, monkeypatch) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("# comment\nPAPERCLAW_API_KEY=local-key\nPAPERCLAW_MODEL=deepseek-v4-flash\n", encoding="utf-8")
    monkeypatch.delenv("PAPERCLAW_API_KEY", raising=False)
    monkeypatch.setenv("PAPERCLAW_MODEL", "keep-me")

    load_dotenv(dotenv_path)

    assert os.environ["PAPERCLAW_API_KEY"] == "local-key"
    assert os.environ["PAPERCLAW_MODEL"] == "keep-me"


def test_openai_compatible_model_sends_user_agent(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "ok", "reasoning_content": "think"}}]}).encode()

    def fake_urlopen(request, timeout):
        assert isinstance(request, urllib.request.Request)
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    model = OpenAICompatibleModel(api_key="k", base_url="https://example.com/v1", model="deepseek-v4-flash")
    turn = model.complete("hello")
    assert turn.content == "ok"
    assert turn.reasoning == "think"
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["user-agent"].startswith("PaperClaw/0.0.1")
    assert headers["accept"] == "application/json"


def test_cli_verification_gate_defaults_to_true() -> None:
    """M-08: both agent and team modes must enable Verify Gate by default."""

    parser = _build_parser()

    agent_args = parser.parse_args(["agent", "test"])
    assert agent_args.enable_verification_gate is True

    team_args = parser.parse_args(["team", "--plan", "plan.json"])
    assert team_args.enable_verification_gate is True


def test_cli_disabling_verification_gate_works() -> None:
    parser = _build_parser()

    agent_args = parser.parse_args(["agent", "--no-enable-verification-gate", "test"])
    assert agent_args.enable_verification_gate is False

    team_args = parser.parse_args(["team", "--plan", "plan.json", "--no-enable-verification-gate"])
    assert team_args.enable_verification_gate is False


def test_cli_backwards_compatible_bare_task_invocation() -> None:
    """Legacy `paperclaw <task>` must default to the agent subcommand."""

    parser = _build_parser()
    argv = ["some task here"]
    if argv and argv[0] not in {"agent", "team", "-h", "--help", "--version", "-v"}:
        argv = ["agent", *argv]
    args = parser.parse_args(argv)
    assert args.command == "agent"
    assert args.task == "some task here"
    assert args.enable_verification_gate is True
