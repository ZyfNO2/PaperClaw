"""Executor isolation boundary for local subprocess and future remote workers."""

from .base import ExecutionHandle, WorkerExecutor
from .contracts import (
    ExecutionRequest,
    ExecutionResult,
    ExecutorStatus,
    TERMINAL_EXECUTOR_STATUSES,
)
from .subprocess import (
    DEFAULT_ALLOWED_ENTRYPOINTS,
    SubprocessExecutionHandle,
    SubprocessWorkerExecutor,
)

__all__ = [
    "DEFAULT_ALLOWED_ENTRYPOINTS",
    "ExecutionHandle",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutorStatus",
    "SubprocessExecutionHandle",
    "SubprocessWorkerExecutor",
    "TERMINAL_EXECUTOR_STATUSES",
    "WorkerExecutor",
]
