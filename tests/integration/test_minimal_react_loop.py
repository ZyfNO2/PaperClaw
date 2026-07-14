from pathlib import Path

import pytest

from conftest import FakeModel, action, done
from paperclaw.agent.flow import AgentRuntime


def test_write_bash_done(tmp_path: Path) -> None:
    model = FakeModel([action("file_write", {"path": "hello.py", "content": "print('PaperClaw v0.01 OK')"}), action("bash", {"command": "python hello.py"}), done()])
    state = AgentRuntime(model).run("create and verify", tmp_path)
    assert state["stop_reason"] == "done" and state["verification_status"] == "verified"
    assert state["history"][1].result.output == "PaperClaw v0.01 OK"


def test_read_edit_bash_done(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('BAD')")
    model = FakeModel([action("file_read", {"path": "app.py"}), action("file_edit", {"path": "app.py", "old_text": "BAD", "new_text": "OK"}), action("bash", {"command": "python app.py"}), done()])
    state = AgentRuntime(model).run("fix app", tmp_path)
    assert state["stop_reason"] == "done" and "OK" in state["history"][2].result.output


def test_grep_read_edit_bash_done(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def value(): return 1\nprint(value())")
    model = FakeModel([action("grep", {"pattern": "def value"}), action("file_read", {"path": "app.py"}), action("file_edit", {"path": "app.py", "old_text": "return 1", "new_text": "return 2"}), action("bash", {"command": "python app.py"}), done()])
    state = AgentRuntime(model).run("change value", tmp_path)
    assert state["stop_reason"] == "done" and state["history"][3].result.output == "2"


def test_path_error_is_recoverable(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("ok")
    model = FakeModel([action("file_read", {"path": "../nope"}), action("file_read", {"path": "ok.txt"}), done()])
    state = AgentRuntime(model).run("read", tmp_path)
    assert not state["history"][0].result.ok and state["history"][1].result.ok


def test_unknown_action_is_repaired(tmp_path: Path) -> None:
    model = FakeModel([action("unknown", {}), action("file_write", {"path": "ok.txt", "content": "ok"}), done()])
    state = AgentRuntime(model).run("write", tmp_path)
    assert state["history"][0].result.error_code == "invalid_model_output" and state["stop_reason"] == "done"


def test_invalid_output_stops_bounded(tmp_path: Path) -> None:
    model = FakeModel(["bad", "still bad"])
    state = AgentRuntime(model).run("fail safely", tmp_path, max_steps=8)
    assert state["stop_reason"] == "invalid_model_output" and state["step_count"] == 2
    assert "invalid_model_output" in model.prompts[1]


def test_done_claim_without_successful_bash_stays_unverified(tmp_path: Path) -> None:
    model = FakeModel([action("file_read", {"path": "missing.txt"}), done()])
    state = AgentRuntime(model).run("claim", tmp_path)
    assert state["verification_status"] == "unverified"


def test_max_steps_stops_loop(tmp_path: Path) -> None:
    model = FakeModel([action("file_write", {"path": f"{i}.txt", "content": "x"}) for i in range(4)])
    state = AgentRuntime(model).run("loop", tmp_path, max_steps=2)
    assert state["stop_reason"] == "max_steps" and state["step_count"] == 2
