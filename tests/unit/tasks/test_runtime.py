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
    lock = Lock()
    windows: dict[str, tuple[float, float]] = {}

    def executor(task, should_cancel):
        started = monotonic()
        barrier.wait(timeout=3)
        sleep(0.2)
        finished = monotonic()
        with lock:
            windows[task.task_id] = (started, finished)
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
    supervisor.start()
    supervisor.notify()
    try:
        assert supervisor.wait_for_terminal("a", timeout=5).status is TaskStatus.SUCCEEDED
        assert supervisor.wait_for_terminal("b", timeout=5).status is TaskStatus.SUCCEEDED
        assert set(windows) == {"a", "b"}
        latest_start = max(start for start, _ in windows.values())
        earliest_finish = min(finish for _, finish in windows.values())
        assert latest_start < earliest_finish
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
