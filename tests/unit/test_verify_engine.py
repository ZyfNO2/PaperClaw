from pathlib import Path

from paperclaw.agent.state import HistoryEntry, initial_state
from paperclaw.agent.verify import build_verification_plan, execute_verification_plan, parse_pytest_summary, summarize_command_result
from paperclaw.tools.base import ToolResult


def test_build_verification_plan_tracks_writes_and_command_claim(tmp_path: Path) -> None:
    shared = initial_state("create hello", tmp_path)
    shared["history"] = [
        HistoryEntry(1, "file_write", {"path": "hello.py", "content": "print('ok')"}, "write", ToolResult(True, "ok")),
        HistoryEntry(2, "bash", {"command": "python hello.py"}, "run", ToolResult(True, "ok", metadata={"exit_code": 0})),
    ]
    shared["step_count"] = 3

    plan = build_verification_plan(shared)

    assert any(claim.claim_id == "claim-verification-command" for claim in plan.task_claims)
    assert any(check.check_type == "file_contains" for check in plan.checks)
    assert any(check.check_type == "file_hash" for check in plan.checks)


def test_execute_verification_plan_requires_relevant_command_after_last_write(tmp_path: Path) -> None:
    (tmp_path / "hello.py").write_text("print('ok')", encoding="utf-8")
    shared = initial_state("create hello", tmp_path)
    shared["history"] = [
        HistoryEntry(1, "file_write", {"path": "hello.py", "content": "print('ok')"}, "write", ToolResult(True, "ok")),
        HistoryEntry(2, "bash", {"command": "echo ok"}, "fake verify", ToolResult(True, "ok", metadata={"exit_code": 0})),
    ]
    shared["step_count"] = 3

    result = execute_verification_plan(shared, build_verification_plan(shared))

    assert result.status == "failed"
    assert result.verified_after_last_write is False
    assert "claim-verification-command" in result.failed_claim_ids


def test_execute_verification_plan_marks_failed_pytest_as_verified_but_failed(tmp_path: Path) -> None:
    (tmp_path / "test_app.py").write_text("def test_fail():\n    assert 1 == 2\n", encoding="utf-8")
    shared = initial_state("run tests", tmp_path)
    shared["history"] = [
        HistoryEntry(1, "file_write", {"path": "test_app.py", "content": "def test_fail():\n    assert 1 == 2\n"}, "write", ToolResult(True, "ok")),
        HistoryEntry(
            2,
            "bash",
            {"command": "pytest -q"},
            "run tests",
            ToolResult(
                False,
                "F\nFAILED test_app.py::test_fail - assert 1 == 2\n= 1 failed in 0.12s =",
                "command_failed",
                {"command": "pytest -q", "command_class": "pytest", "exit_code": 1, "duration_ms": 120, "timed_out": False, "truncated": False},
            ),
        ),
    ]
    shared["step_count"] = 3

    result = execute_verification_plan(shared, build_verification_plan(shared))

    assert result.status == "failed"
    assert result.verified_after_last_write is True
    assert result.checks[-1].exit_code == 1


def test_parse_pytest_summary_extracts_counts_and_failed_names() -> None:
    summary = parse_pytest_summary(
        "F.\nFAILED tests/test_app.py::test_fail - assert 1 == 2\n======================== 1 failed, 1 passed, 1 skipped in 0.34s ========================"
    )

    assert summary["failed_count"] == 1
    assert summary["passed_count"] == 1
    assert summary["skipped_count"] == 1
    assert summary["duration_seconds"] == 0.34
    assert summary["failed_test_names"] == ["tests/test_app.py::test_fail"]


def test_parse_pytest_summary_extracts_simple_pass_footer() -> None:
    summary = parse_pytest_summary(".                                                                        [100%]\n1 passed in 0.02s")

    assert summary["passed_count"] == 1
    assert summary["failed_count"] is None
    assert summary["duration_seconds"] == 0.02


def test_summarize_command_result_keeps_generic_shell_metadata() -> None:
    entry = HistoryEntry(
        2,
        "bash",
        {"command": "python hello.py"},
        "run",
        ToolResult(
            True,
            "ok",
            metadata={
                "command": "python hello.py",
                "command_class": "shell",
                "cwd": "G:/PaperClaw",
                "exit_code": 0,
                "timed_out": False,
                "duration_ms": 88,
                "started_at": "2026-07-13T00:00:00+00:00",
                "finished_at": "2026-07-13T00:00:01+00:00",
                "truncated": False,
            },
        ),
    )

    summary = summarize_command_result(entry)

    assert summary["command"] == "python hello.py"
    assert summary["command_class"] == "shell"
    assert summary["exit_code"] == 0


def test_execute_verification_plan_checks_written_file_hash(tmp_path: Path) -> None:
    content = "print('ok')\n"
    (tmp_path / "hello.py").write_text(content, encoding="utf-8")
    shared = initial_state("create hello", tmp_path)
    shared["history"] = [
        HistoryEntry(1, "file_write", {"path": "hello.py", "content": content}, "write", ToolResult(True, "ok")),
        HistoryEntry(2, "bash", {"command": "python hello.py"}, "run", ToolResult(True, "ok", metadata={"command": "python hello.py", "command_class": "shell", "exit_code": 0, "timed_out": False, "truncated": False})),
    ]
    shared["step_count"] = 3

    result = execute_verification_plan(shared, build_verification_plan(shared))

    assert result.status == "passed"
    assert any("sha256 matches" in check.observed for check in result.checks)
