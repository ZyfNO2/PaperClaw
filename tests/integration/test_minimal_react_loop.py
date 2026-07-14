from pathlib import Path

from paperclaw.agent.flow import AgentRuntime
from tests.helpers import FakeModel, action, done, reflect


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


def test_verification_gate_accepts_relevant_success_path(tmp_path: Path) -> None:
    model = FakeModel([action("file_write", {"path": "hello.py", "content": "print('PaperClaw v0.01 OK')"}), action("bash", {"command": "python hello.py"}), done(result="ok", verification="python hello.py => PaperClaw v0.01 OK")])
    state = AgentRuntime(model, enable_verification_gate=True).run("create hello and verify", tmp_path)
    assert state["stop_reason"] == "completed_verified"
    assert state["verification_result"].status == "passed"
    assert state["verification_result"].verified_after_last_write is True
    assert state["reflection_decision"].decision == "accept"


def test_verification_gate_rejects_irrelevant_success_command(tmp_path: Path) -> None:
    model = FakeModel([action("file_write", {"path": "hello.py", "content": "print('PaperClaw v0.01 OK')"}), action("bash", {"command": "echo ok"}), done(result="ok", verification="echo ok"), reflect("blocked", failed_claim_ids=["claim-verification-command"], reason_code="verification_failed")])
    state = AgentRuntime(model, enable_verification_gate=True).run("create hello and verify", tmp_path)
    assert state["stop_reason"] == "verification_failed"
    assert "claim-verification-command" in state["verification_result"].failed_claim_ids


def test_reflection_can_request_repair_then_accept(tmp_path: Path) -> None:
    model = FakeModel(
        [
            action("file_write", {"path": "hello.py", "content": "print('PaperClaw v0.01 OK')"}),
            action("bash", {"command": "echo ok"}),
            done(result="first try", verification="echo ok"),
            reflect("repair", failed_claim_ids=["claim-verification-command"], next_action="run the actual file", reason_code="verification_failed"),
            action("bash", {"command": "python hello.py"}),
            done(result="fixed", verification="python hello.py => PaperClaw v0.01 OK"),
        ]
    )
    state = AgentRuntime(model, enable_verification_gate=True).run("create hello and verify", tmp_path)
    assert state["stop_reason"] == "completed_verified"
    assert state["result"] == "fixed"
    assert state["verification_result"].status == "passed"


def test_reflection_limit_blocks_repeated_failure(tmp_path: Path) -> None:
    model = FakeModel(
        [
            action("file_write", {"path": "hello.py", "content": "print('PaperClaw v0.01 OK')"}),
            action("bash", {"command": "echo ok"}),
            done(result="first try", verification="echo ok"),
            reflect("repair", failed_claim_ids=["claim-verification-command"], next_action="try again", reason_code="verification_failed"),
            done(result="second try", verification="echo ok"),
        ]
    )
    state = AgentRuntime(model, enable_verification_gate=True).run("create hello and verify", tmp_path)
    assert state["stop_reason"] == "verification_failed"
    assert state["reflection_decision"].decision == "blocked"


def test_verification_gate_rejects_stale_verification_after_new_edit(tmp_path: Path) -> None:
    model = FakeModel(
        [
            action("file_write", {"path": "hello.py", "content": "print('v1')"}),
            action("bash", {"command": "python hello.py"}),
            action("file_edit", {"path": "hello.py", "old_text": "v1", "new_text": "v2"}),
            done(result="stale verify", verification="python hello.py => v1"),
            reflect("blocked", failed_claim_ids=["claim-verification-command"], reason_code="verification_failed"),
        ]
    )
    state = AgentRuntime(model, enable_verification_gate=True).run("update hello and verify", tmp_path)
    assert state["verification_result"].verified_after_last_write is False
    assert state["stop_reason"] == "verification_failed"


def test_reflection_can_fix_failed_pytest_then_complete(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def answer():\n    return 1\n", encoding="utf-8")
    (tmp_path / "test_app.py").write_text("from app import answer\n\ndef test_answer():\n    assert answer() == 2\n", encoding="utf-8")
    model = FakeModel(
        [
            action("bash", {"command": "pytest -q"}),
            done(result="tests passed", verification="pytest -q"),
            reflect("repair", failed_claim_ids=["claim-verification-command"], next_action="fix answer and rerun pytest", reason_code="verification_failed"),
            action("file_edit", {"path": "app.py", "old_text": "return 1", "new_text": "return 2"}),
            action("bash", {"command": "pytest -q"}),
            done(result="tests passed after fix", verification="pytest -q"),
        ]
    )
    state = AgentRuntime(model, enable_verification_gate=True).run("make tests pass", tmp_path)
    assert state["stop_reason"] == "completed_verified"
    assert state["verification_result"].status == "passed"
    assert state["verification_result"].verified_after_last_write is True
