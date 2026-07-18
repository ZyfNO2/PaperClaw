from __future__ import annotations

from pathlib import Path
from threading import Barrier, Lock
from time import monotonic, sleep

from paperclaw.tasks import (
    BackgroundTaskSupervisor,
    SQLiteDurableTaskStore,
    TaskExecutionResult,
    TaskSpec,
    TaskStatus,
)


def create(store: SQLiteDurableTaskStore, task_id: str) -> None:
    store.create_task(
        TaskSpec(
            task_id=task_id,
            objective=task_id,
            workspace=".",
            timeout_seconds=5,
            max_attempts=2,
        )
    )


def test_two_background_tasks_execute_concurrently(tmp_path: Path) -> None:
    store = SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    barrier = Barrier(2)

    def executor(task, should_cancel):
        barrier.wait(timeout=3)
        sleep(0.2)
        return TaskExecutionResult(
            TaskStatus.SUCCEEDED,
            output={"task": task.task_id},
            model_calls=1,
        )

    supervisor = BackgroundTaskSupervisor(
        store,
        executor,
        max_concurrency=2,
        provider_concurrency=2,
        heartbeat_seconds=0.2,
        lease_seconds=2,
        poll_seconds=0.02,
    )
    create(store, "a")
    create(store, "b")
    started = monotonic()
    supervisor.start()
    supervisor.notify()
    try:
        assert supervisor.wait_for_terminal("a", timeout=5).status is TaskStatus.SUCCEEDED
        assert supervisor.wait_for_terminal("b", timeout=5).status is TaskStatus.SUCCEEDED
        assert monotonic() - started < 0.42
    finally:
        supervisor.stop()


def test_provider_semaphore_limits_active_executors(tmp_path: Path) -> None:
    store = SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    lock = Lock()
    active = 0
    maximum = 0

    def executor(task, should_cancel):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            sleep(0.08)
            return TaskExecutionResult(TaskStatus.SUCCEEDED)
        finally:
            with lock:
                active -= 1

    supervisor = BackgroundTaskSupervisor(
        store,
        executor,
        max_concurrency=3,
        provider_concurrency=1,
        heartbeat_seconds=0.2,
        lease_seconds=2,
        poll_seconds=0.01,
    )
    for task_id in ("a", "b", "c"):
        create(store, task_id)
    supervisor.start()
    supervisor.notify()
    try:
        for task_id in ("a", "b", "c"):
            assert supervisor.wait_for_terminal(task_id, timeout=5).terminal
        assert maximum == 1
    finally:
        supervisor.stop()


def test_retryable_failure_requeues_before_succeeding(tmp_path: Path) -> None:
    store = SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    attempts: dict[str, int] = {}

    def executor(task, should_cancel):
        attempts[task.task_id] = attempts.get(task.task_id, 0) + 1
        if attempts[task.task_id] == 1:
            raise RuntimeError("transient_provider_failure")
        return TaskExecutionResult(TaskStatus.SUCCEEDED, output={"attempt": 2})

    supervisor = BackgroundTaskSupervisor(
        store,
        executor,
        max_concurrency=1,
        provider_concurrency=1,
        heartbeat_seconds=0.2,
        lease_seconds=2,
        poll_seconds=0.01,
    )
    create(store, "retry")
    supervisor.start()
    supervisor.notify()
    try:
        result = supervisor.wait_for_terminal("retry", timeout=5)
        assert result.status is TaskStatus.SUCCEEDED
        assert result.attempt == 2
        assert attempts["retry"] == 2
    finally:
        supervisor.stop()


def test_explicit_cancel_propagates_to_cooperative_executor(tmp_path: Path) -> None:
    store = SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")

    def executor(task, should_cancel):
        while not should_cancel():
            sleep(0.01)
        return TaskExecutionResult(
            TaskStatus.CANCELLED,
            stop_reason="cancel_requested",
        )

    supervisor = BackgroundTaskSupervisor(
        store,
        executor,
        max_concurrency=1,
        provider_concurrency=1,
        heartbeat_seconds=0.2,
        lease_seconds=2,
        poll_seconds=0.01,
    )
    create(store, "cancel")
    supervisor.start()
    supervisor.notify()
    try:
        deadline = monotonic() + 3
        while store.get_task("cancel").status is not TaskStatus.RUNNING:
            assert monotonic() < deadline
            sleep(0.01)
        store.request_cancel("cancel", reason="test_cancel")
        supervisor.notify()
        result = supervisor.wait_for_terminal("cancel", timeout=5)
        assert result.status is TaskStatus.CANCELLED
        assert result.stop_reason == "cancel_requested"
    finally:
        supervisor.stop()
