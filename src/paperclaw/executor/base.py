"""Executor protocols consumed by local and future remote execution backends."""

from __future__ import annotations

from typing import Protocol

from .contracts import ExecutionRequest, ExecutionResult


class ExecutionHandle(Protocol):
    @property
    def execution_id(self) -> str: ...

    @property
    def pid(self) -> int | None: ...

    def poll(self) -> ExecutionResult | None: ...

    def wait(self, timeout: float | None = None) -> ExecutionResult | None: ...

    def cancel(self, reason: str = "cancel_requested") -> ExecutionResult: ...

    def close(self) -> None: ...


class WorkerExecutor(Protocol):
    def start(self, request: ExecutionRequest) -> ExecutionHandle: ...


__all__ = ["ExecutionHandle", "WorkerExecutor"]
