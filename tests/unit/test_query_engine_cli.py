"""Phase C compatibility tests for the single-agent CLI path."""

from __future__ import annotations

import json
from pathlib import Path

from paperclaw.cli import main
from paperclaw.models.adapters import OpenAICompatibleModel
from tests.helpers import FakeModel, done


def test_single_agent_cli_returns_query_engine_result(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    model = FakeModel([done(result="cli-ok")])
    monkeypatch.setattr(
        OpenAICompatibleModel,
        "from_env",
        staticmethod(lambda: model),
    )

    exit_code = main(
        [
            "agent",
            "finish directly",
            "--workspace",
            str(tmp_path),
            "--max-steps",
            "3",
            "--max-model-calls",
            "2",
            "--max-tool-calls",
            "2",
            "--no-enable-verification-gate",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["query_engine"]["status"] == "completed"
    assert payload["query_engine"]["model_calls"] == 1
    assert payload["result"] == "cli-ok"


def test_legacy_positional_task_still_routes_to_agent(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        OpenAICompatibleModel,
        "from_env",
        staticmethod(lambda: FakeModel([done(result="legacy-ok")])),
    )

    exit_code = main(
        [
            "legacy task",
            "--workspace",
            str(tmp_path),
            "--no-enable-verification-gate",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["query_engine"]["status"] == "completed"
    assert payload["result"] == "legacy-ok"
