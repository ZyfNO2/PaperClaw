from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from paperclaw.executor import ExecutionResult, ExecutorStatus
from paperclaw.tasks.contracts import TaskRecord, TaskStatus
from paperclaw.tasks.process_executor import SubprocessSubagentTaskExecutor


class FakeHandle:
    def __init__(self, result: ExecutionResult) -> None:
        self._result = result
        self.closed = False
        self.cancelled = False

    @property
    def execution_id(self) -> str:
        return self._result.execution_id

    @property
    def pid(self) -> int | None:
        return self._result.pid

    def poll(self) -> ExecutionResult | None:
        return self._result

    def wait(self, timeout: float | None = None) -> ExecutionResult | None:
        del timeout
        return self._result

    def cancel(self, reason: str = "cancel_requested") -> ExecutionResult:
        del reason
        self.cancelled = True
        return self._result

    def close(self) -> None:
        self.closed = True


class FakeExecutor:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.request = None
        self.handle = FakeHandle(result)

    def start(self, request):
        self.request = request
        return self.handle


def _task(tmp_path: Path, *, metadata: dict[str, Any] | None = None) -> TaskRecord:
    return TaskRecord(
        task_id="task-1",
        parent_run_id="run-1",
        objective="inspect one module",
        workspace=str(tmp_path),
        status=TaskStatus.RUNNING,
        version=2,
        attempt=1,
        max_attempts=2,
        max_steps=4,
        timeout_seconds=10.0,
        cancel_requested=False,
        lease_owner="worker",
        lease_expires_at=None,
        last_heartbeat_at=None,
        side_effect_state="none",
        created_at=1.0,
        updated_at=2.0,
        started_at=2.0,
        completed_at=None,
        stop_reason=None,
        output=None,
        error=None,
        metadata=metadata
        or {
            "allowed_paths": ["src"],
            "writable_paths": [],
            "allowed_tools": ["file_read", "grep"],
        },
        dependencies=(),
    )


def _execution(status: ExecutorStatus, output=None) -> ExecutionResult:
    return ExecutionResult(
        execution_id="exec-1",
        task_id="task-1",
        status=status,
        output=output,
        exit_code=0 if status is ExecutorStatus.SUCCEEDED else 1,
        pid=123,
    )


def test_subprocess_task_executor_maps_success_contract(tmp_path: Path) -> None:
    child_output = {
        "status": "succeeded",
        "output": {"summary": "done"},
        "error": None,
        "stop_reason": None,
        "side_effect_state": "none",
        "model_calls": 3,
        "tool_calls": 2,
        "input_tokens": 4,
        "output_tokens": 5,
    }
    fake = FakeExecutor(_execution(ExecutorStatus.SUCCEEDED, child_output))
    adapter = SubprocessSubagentTaskExecutor(fake)  # type: ignore[arg-type]

    result = adapter(_task(tmp_path), lambda: False)

    assert result.status is TaskStatus.SUCCEEDED
    assert result.output == {"summary": "done"}
    assert result.model_calls == 3
    assert result.tool_calls == 2
    assert fake.request.entrypoint == "tasks.subagent.env.v1"
    assert "api_key" not in str(fake.request.payload).lower()
    assert fake.handle.closed is True


def test_read_only_cancel_stays_cancelled(tmp_path: Path) -> None:
    fake = FakeExecutor(_execution(ExecutorStatus.CANCELLED))
    adapter = SubprocessSubagentTaskExecutor(fake)  # type: ignore[arg-type]

    result = adapter(_task(tmp_path), lambda: False)

    assert result.status is TaskStatus.CANCELLED
    assert result.side_effect_state == "none"


def test_write_capable_cancel_becomes_unknown_outcome(tmp_path: Path) -> None:
    task = _task(
        tmp_path,
        metadata={
            "allowed_paths": ["."],
            "writable_paths": ["src"],
            "allowed_tools": ["file_write"],
        },
    )
    fake = FakeExecutor(_execution(ExecutorStatus.CANCELLED))
    adapter = SubprocessSubagentTaskExecutor(fake)  # type: ignore[arg-type]

    result = adapter(task, lambda: False)

    assert result.status is TaskStatus.UNKNOWN_OUTCOME
    assert result.side_effect_state == "unknown"


def test_bash_capability_is_conservatively_write_capable(tmp_path: Path) -> None:
    task = replace(
        _task(tmp_path),
        metadata={
            "allowed_paths": ["."],
            "writable_paths": [],
            "allowed_tools": ["bash"],
        },
    )
    fake = FakeExecutor(_execution(ExecutorStatus.TIMED_OUT))
    adapter = SubprocessSubagentTaskExecutor(fake)  # type: ignore[arg-type]

    result = adapter(task, lambda: False)

    assert result.status is TaskStatus.UNKNOWN_OUTCOME


def test_read_only_child_crash_maps_failed_without_raw_message(tmp_path: Path) -> None:
    execution = ExecutionResult(
        execution_id="exec-1",
        task_id="task-1",
        status=ExecutorStatus.CRASHED,
        error_code="child_exception",
        error_type="RuntimeError",
        exit_code=4,
        pid=123,
    )
    adapter = SubprocessSubagentTaskExecutor(FakeExecutor(execution))  # type: ignore[arg-type]

    result = adapter(_task(tmp_path), lambda: False)

    assert result.status is TaskStatus.FAILED
    assert result.error["executor_error_type"] == "RuntimeError"
    assert "traceback" not in str(result.error).lower()


def test_invalid_child_task_result_fails_closed(tmp_path: Path) -> None:
    fake = FakeExecutor(_execution(ExecutorStatus.SUCCEEDED, {"status": "running"}))
    adapter = SubprocessSubagentTaskExecutor(fake)  # type: ignore[arg-type]

    result = adapter(_task(tmp_path), lambda: False)

    assert result.status is TaskStatus.FAILED
    assert result.error == {"code": "invalid_subprocess_task_result"}
