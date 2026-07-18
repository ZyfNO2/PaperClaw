from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.tasks import (
    SQLiteDurableTaskStore,
    TaskExecutionResult,
    TaskSpec,
    TaskStatus,
)
from paperclaw.tasks.contracts import TaskConflictError


class Clock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def store(tmp_path: Path, clock: Clock) -> SQLiteDurableTaskStore:
    return SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3", clock=clock)


def spec(task_id: str, *, dependencies=(), idempotency_key=None) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        objective=f"execute {task_id}",
        workspace=".",
        dependencies=tuple(dependencies),
        idempotency_key=idempotency_key,
        max_attempts=2,
        metadata={"allowed_tools": ["file_read"]},
    )


def complete(
    task_store: SQLiteDurableTaskStore,
    task_id: str,
    status: TaskStatus = TaskStatus.SUCCEEDED,
):
    claimed = task_store.claim_next("worker", lease_seconds=10)
    assert claimed is not None and claimed.task_id == task_id
    running = task_store.start_task(
        task_id,
        "worker",
        expected_version=claimed.version,
    )
    return task_store.complete_task(
        task_id,
        "worker",
        expected_version=running.version,
        result=TaskExecutionResult(
            status,
            output={"value": task_id} if status is TaskStatus.SUCCEEDED else None,
            error=None if status is TaskStatus.SUCCEEDED else {"code": "failed"},
            stop_reason=status.value,
        ),
    )


def test_idempotent_create_returns_same_task_and_rejects_payload_change(
    tmp_path: Path,
) -> None:
    clock = Clock()
    task_store = store(tmp_path, clock)

    first, created = task_store.create_task(spec("a", idempotency_key="same"))
    replay, replay_created = task_store.create_task(
        spec("a", idempotency_key="same")
    )

    assert created is True
    assert replay_created is False
    assert replay.task_id == first.task_id
    with pytest.raises(TaskConflictError):
        task_store.create_task(
            TaskSpec(
                task_id="different",
                objective="different payload",
                workspace=".",
                idempotency_key="same",
            )
        )


def test_dependency_success_queues_child_and_failure_blocks_child(tmp_path: Path) -> None:
    clock = Clock()
    task_store = store(tmp_path, clock)
    task_store.create_task(spec("parent"))
    child, _ = task_store.create_task(spec("child", dependencies=["parent"]))
    assert child.status is TaskStatus.WAITING_DEPENDENCY

    complete(task_store, "parent")
    assert task_store.get_task("child").status is TaskStatus.QUEUED
    complete(task_store, "child")

    task_store.create_task(spec("failed-parent"))
    blocked, _ = task_store.create_task(
        spec("blocked-child", dependencies=["failed-parent"])
    )
    assert blocked.status is TaskStatus.WAITING_DEPENDENCY
    complete(task_store, "failed-parent", TaskStatus.FAILED)
    assert task_store.get_task("blocked-child").status is TaskStatus.BLOCKED


def test_expired_safe_lease_requeues_but_unknown_side_effect_does_not_retry(
    tmp_path: Path,
) -> None:
    clock = Clock()
    task_store = store(tmp_path, clock)
    task_store.create_task(spec("safe"))
    claimed = task_store.claim_next("worker-a", lease_seconds=5)
    assert claimed is not None
    task_store.start_task("safe", "worker-a", expected_version=claimed.version)
    clock.advance(6)

    recovered = task_store.recover_expired_leases()
    assert recovered[0].status is TaskStatus.QUEUED

    claimed_again = task_store.claim_next("worker-b", lease_seconds=5)
    assert claimed_again is not None
    running = task_store.start_task(
        "safe", "worker-b", expected_version=claimed_again.version
    )
    task_store.mark_side_effect_state(
        "safe",
        "worker-b",
        expected_version=running.version,
        state="unknown",
    )
    clock.advance(6)

    recovered_again = task_store.recover_expired_leases()
    assert recovered_again[0].status is TaskStatus.UNKNOWN_OUTCOME
    assert recovered_again[0].stop_reason == "lease_expired_after_possible_side_effect"


def test_cancel_running_task_is_persisted_and_events_are_monotonic(tmp_path: Path) -> None:
    clock = Clock()
    task_store = store(tmp_path, clock)
    task_store.create_task(spec("cancel-me"))
    claimed = task_store.claim_next("worker", lease_seconds=20)
    assert claimed is not None
    task_store.start_task("cancel-me", "worker", expected_version=claimed.version)

    cancelled = task_store.request_cancel("cancel-me", reason="user_requested")
    assert cancelled.status is TaskStatus.RUNNING
    assert cancelled.cancel_requested is True

    events = task_store.list_events("cancel-me")
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].event_type == "task.cancel_requested"
