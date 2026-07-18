"""Application service for durable background task APIs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .contracts import TaskEvent, TaskRecord, TaskSpec, TaskStatus
from .runtime import BackgroundTaskSupervisor
from .store import SQLiteDurableTaskStore


class TaskApplicationService:
    def __init__(
        self,
        store: SQLiteDurableTaskStore,
        supervisor: BackgroundTaskSupervisor,
    ) -> None:
        self.store = store
        self.supervisor = supervisor

    def submit(
        self,
        *,
        objective: str,
        workspace: str,
        parent_run_id: str | None = None,
        task_id: str | None = None,
        dependencies: Sequence[str] = (),
        max_steps: int = 20,
        timeout_seconds: float = 600.0,
        max_attempts: int = 2,
        idempotency_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[TaskRecord, bool]:
        spec = TaskSpec(
            task_id=task_id or f"task-{uuid4().hex[:16]}",
            parent_run_id=parent_run_id,
            objective=objective,
            workspace=workspace,
            dependencies=tuple(dependencies),
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            metadata=dict(metadata or {}),
        )
        task, created = self.store.create_task(spec)
        self.supervisor.start()
        self.supervisor.notify()
        return task, created

    def get(self, task_id: str) -> TaskRecord:
        return self.store.get_task(task_id)

    def list(
        self,
        *,
        parent_run_id: str | None = None,
        statuses: Sequence[TaskStatus | str] | None = None,
        limit: int = 200,
    ) -> tuple[TaskRecord, ...]:
        return self.store.list_tasks(
            parent_run_id=parent_run_id,
            statuses=statuses,
            limit=limit,
        )

    def cancel(self, task_id: str, *, reason: str = "user_requested") -> TaskRecord:
        task = self.store.request_cancel(task_id, reason=reason)
        self.supervisor.notify()
        return task

    def events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> tuple[TaskEvent, ...]:
        return self.store.list_events(
            task_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def output(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "terminal": task.terminal,
            "output": task.output,
            "error": task.error,
            "stop_reason": task.stop_reason,
            "side_effect_state": task.side_effect_state,
        }

    def recover(self) -> tuple[TaskRecord, ...]:
        recovered = self.store.recover_expired_leases()
        self.supervisor.notify()
        return recovered

    def shutdown(self, *, wait: bool = True) -> None:
        self.supervisor.stop(wait=wait)


__all__ = ["TaskApplicationService"]
