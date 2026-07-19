"""Durable task adapter backed by the v0.23 subprocess executor boundary."""

from __future__ import annotations

from time import sleep
from typing import Any, Mapping
from uuid import uuid4

from paperclaw.executor import (
    ExecutionRequest,
    ExecutionResult,
    ExecutorStatus,
    SubprocessWorkerExecutor,
)

from .contracts import TaskExecutionResult, TaskRecord, TaskStatus


class SubprocessSubagentTaskExecutor:
    """Execute one durable single-Worker task in a fresh child process.

    This adapter is intentionally limited to the durable task path. Parallel
    subprocess writers are not enabled while file leases remain process-local.
    """

    ENTRYPOINT = "tasks.subagent.env.v1"

    def __init__(
        self,
        executor: SubprocessWorkerExecutor | None = None,
        *,
        poll_seconds: float = 0.025,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._executor = executor or SubprocessWorkerExecutor(
            allowed_entrypoints={self.ENTRYPOINT}
        )
        self._poll_seconds = poll_seconds

    def __call__(self, task: TaskRecord, should_cancel) -> TaskExecutionResult:
        # Leave a small parent-side margin so BackgroundTaskSupervisor's outer
        # asyncio timeout does not abandon the thread before the child is reaped.
        child_timeout = max(0.05, float(task.timeout_seconds) * 0.9)
        request = ExecutionRequest(
            execution_id=f"task-exec-{uuid4().hex[:16]}",
            task_id=task.task_id,
            entrypoint=self.ENTRYPOINT,
            payload={"task": task.to_dict()},
            workspace=task.workspace,
            timeout_seconds=child_timeout,
            metadata={"execution_mode": "subprocess", "contract_version": 1},
        )
        handle = self._executor.start(request)
        try:
            while True:
                if should_cancel():
                    execution = handle.cancel("cancel_requested")
                    return self._map_executor_terminal(task, execution)
                execution = handle.poll()
                if execution is not None:
                    return self._map_executor_terminal(task, execution)
                sleep(self._poll_seconds)
        finally:
            handle.close()

    def _map_executor_terminal(
        self,
        task: TaskRecord,
        execution: ExecutionResult,
    ) -> TaskExecutionResult:
        if execution.status is ExecutorStatus.SUCCEEDED:
            return _task_execution_result_from_output(execution.output)

        may_have_side_effects = _task_may_write(task)
        if execution.status is ExecutorStatus.CANCELLED:
            terminal = TaskStatus.UNKNOWN_OUTCOME if may_have_side_effects else TaskStatus.CANCELLED
        elif execution.status is ExecutorStatus.TIMED_OUT:
            terminal = TaskStatus.UNKNOWN_OUTCOME if may_have_side_effects else TaskStatus.TIMED_OUT
        elif execution.status is ExecutorStatus.UNKNOWN_OUTCOME:
            terminal = TaskStatus.UNKNOWN_OUTCOME
        else:
            terminal = TaskStatus.UNKNOWN_OUTCOME if may_have_side_effects else TaskStatus.FAILED

        side_effect_state = "unknown" if terminal is TaskStatus.UNKNOWN_OUTCOME else "none"
        return TaskExecutionResult(
            terminal,
            error={
                "code": "subprocess_execution_terminal",
                "executor_status": execution.status.value,
                "executor_error_code": execution.error_code,
                "executor_error_type": execution.error_type,
                "exit_code": execution.exit_code,
                "termination_method": execution.termination_method,
            },
            stop_reason=f"subprocess_{execution.status.value}",
            side_effect_state=side_effect_state,
        )


def _task_execution_result_from_output(
    value: Mapping[str, Any] | None,
) -> TaskExecutionResult:
    if not isinstance(value, Mapping):
        return TaskExecutionResult(
            TaskStatus.FAILED,
            error={"code": "invalid_subprocess_task_result"},
            stop_reason="invalid_subprocess_task_result",
        )
    try:
        status = TaskStatus(str(value.get("status") or ""))
        output = value.get("output")
        error = value.get("error")
        return TaskExecutionResult(
            status,
            output=dict(output) if isinstance(output, Mapping) else None,
            error=dict(error) if isinstance(error, Mapping) else None,
            stop_reason=value.get("stop_reason") if isinstance(value.get("stop_reason"), str) else None,
            side_effect_state=str(value.get("side_effect_state") or "none"),
            model_calls=_nonnegative_int(value.get("model_calls")),
            tool_calls=_nonnegative_int(value.get("tool_calls")),
            input_tokens=_nonnegative_int(value.get("input_tokens")),
            output_tokens=_nonnegative_int(value.get("output_tokens")),
        )
    except (ValueError, TypeError):
        return TaskExecutionResult(
            TaskStatus.FAILED,
            error={"code": "invalid_subprocess_task_result"},
            stop_reason="invalid_subprocess_task_result",
        )


def _task_may_write(task: TaskRecord) -> bool:
    metadata = task.metadata
    writable_paths = metadata.get("writable_paths")
    if isinstance(writable_paths, list) and any(
        isinstance(path, str) and path.strip() for path in writable_paths
    ):
        return True
    allowed_tools = metadata.get("allowed_tools")
    if isinstance(allowed_tools, list):
        return bool(
            {tool for tool in allowed_tools if isinstance(tool, str)}
            & {"file_write", "file_edit", "bash"}
        )
    return False


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


__all__ = ["SubprocessSubagentTaskExecutor"]
