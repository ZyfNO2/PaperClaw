from __future__ import annotations

import math
from pathlib import Path

import pytest

from paperclaw.executor import ExecutionRequest, ExecutorStatus, SubprocessWorkerExecutor


DIAGNOSTICS = {
    "executor.echo.v1",
    "executor.sleep.v1",
    "executor.crash.v1",
    "executor.exit_no_result.v1",
}


def _request(
    workspace: Path,
    entrypoint: str,
    payload: dict | None = None,
    *,
    timeout: float = 5.0,
) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=f"exec-{entrypoint}",
        task_id="task-1",
        entrypoint=entrypoint,
        payload=payload or {},
        workspace=str(workspace),
        timeout_seconds=timeout,
    )


def _executor() -> SubprocessWorkerExecutor:
    return SubprocessWorkerExecutor(
        allowed_entrypoints=DIAGNOSTICS,
        terminate_grace_seconds=0.2,
        kill_grace_seconds=1.5,
    )


def test_subprocess_echo_success_and_stable_wait(tmp_path: Path) -> None:
    handle = _executor().start(_request(tmp_path, "executor.echo.v1", {"value": 7}))
    try:
        result = handle.wait(timeout=10)
        assert result is not None
        assert result.status is ExecutorStatus.SUCCEEDED
        assert result.output == {"echo": {"value": 7}}
        assert result.exit_code == 0
        assert result.pid == handle.pid
        assert handle.wait(timeout=0) == result
    finally:
        handle.close()


def test_subprocess_rejects_non_allowlisted_entrypoint(tmp_path: Path) -> None:
    executor = _executor()
    with pytest.raises(ValueError, match="not allowlisted"):
        executor.start(_request(tmp_path, "tasks.subagent.env.v1"))


def test_execution_request_rejects_invalid_workspace(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ValueError)):
        _request(tmp_path / "missing", "executor.echo.v1")


def test_execution_request_rejects_non_json_payload(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):
        ExecutionRequest(
            execution_id="bad-json",
            task_id="task",
            entrypoint="executor.echo.v1",
            payload={"value": {1, 2, 3}},
            workspace=str(tmp_path),
            timeout_seconds=1,
        )
    with pytest.raises(ValueError, match="JSON-serializable"):
        ExecutionRequest(
            execution_id="bad-nan",
            task_id="task",
            entrypoint="executor.echo.v1",
            payload={"value": math.nan},
            workspace=str(tmp_path),
            timeout_seconds=1,
        )


def test_child_exception_is_bounded_crash_without_message_or_traceback(tmp_path: Path) -> None:
    handle = _executor().start(_request(tmp_path, "executor.crash.v1"))
    try:
        result = handle.wait(timeout=10)
        assert result is not None
        assert result.status is ExecutorStatus.CRASHED
        assert result.error_code == "child_exception"
        assert result.error_type == "RuntimeError"
        payload = result.to_dict()
        assert "traceback" not in str(payload).lower()
        assert "diagnostic child crash" not in str(payload)
    finally:
        handle.close()


def test_child_exit_without_result_is_classified_crashed(tmp_path: Path) -> None:
    handle = _executor().start(
        _request(tmp_path, "executor.exit_no_result.v1", {"exit_code": 23})
    )
    try:
        result = handle.wait(timeout=10)
        assert result is not None
        assert result.status is ExecutorStatus.CRASHED
        assert result.error_code == "child_exited_without_result"
        assert result.exit_code == 23
    finally:
        handle.close()


def test_request_timeout_terminates_process_tree_before_reporting_terminal(tmp_path: Path) -> None:
    handle = _executor().start(
        _request(tmp_path, "executor.sleep.v1", {"seconds": 10}, timeout=0.2)
    )
    try:
        result = handle.wait(timeout=10)
        assert result is not None
        assert result.status in {ExecutorStatus.TIMED_OUT, ExecutorStatus.UNKNOWN_OUTCOME}
        if result.status is ExecutorStatus.TIMED_OUT:
            assert handle._process.poll() is not None
            assert result.termination_method in {"terminate", "kill", "already_exited"}
    finally:
        handle.close()


def test_cancel_terminates_child_and_is_idempotent(tmp_path: Path) -> None:
    handle = _executor().start(
        _request(tmp_path, "executor.sleep.v1", {"seconds": 10}, timeout=30)
    )
    try:
        result = handle.cancel("test_cancel")
        assert result.status in {ExecutorStatus.CANCELLED, ExecutorStatus.UNKNOWN_OUTCOME}
        if result.status is ExecutorStatus.CANCELLED:
            assert handle._process.poll() is not None
        assert handle.cancel("again") == result
    finally:
        handle.close()


def test_wait_timeout_does_not_implicitly_kill_child(tmp_path: Path) -> None:
    handle = _executor().start(
        _request(tmp_path, "executor.sleep.v1", {"seconds": 1}, timeout=30)
    )
    try:
        assert handle.wait(timeout=0.01) is None
        result = handle.cancel("cleanup")
        assert result.status in {ExecutorStatus.CANCELLED, ExecutorStatus.UNKNOWN_OUTCOME}
    finally:
        handle.close()
