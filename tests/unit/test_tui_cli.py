"""CLI integration tests for the optional v0.06 TUI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

from paperclaw.cli import main
from paperclaw.models.adapters import OpenAICompatibleModel
from tests.helpers import FakeModel, done


def test_explicit_no_tui_uses_standard_agent_fallback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        OpenAICompatibleModel,
        "from_env",
        staticmethod(lambda: FakeModel([done(result="fallback-ok")])),
    )

    exit_code = main(
        [
            "tui",
            "finish through fallback",
            "--no-tui",
            "--workspace",
            str(tmp_path),
            "--no-enable-verification-gate",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["query_engine"]["status"] == "completed"
    assert payload["result"] == "fallback-ok"
    assert "Falling back to the standard single-agent CLI" in captured.err


def test_no_tui_without_task_returns_clear_usage_error(capsys) -> None:
    exit_code = main(["tui", "--no-tui"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "paperclaw agent <task>" in captured.err
