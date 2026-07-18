from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
import queue

import pytest

from paperclaw.tasks.contracts import TaskExecutionResult, TaskLeaseError, TaskSpec, TaskStatus
from paperclaw.tasks.distributed_store import FencedSQLiteDurableTaskStore


def _spec(task_id: str, workspace: Path, *, max_attempts: int = 3) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        objective=f"execute {task_id}",
        workspace=str(workspace),
        max_steps=2,
        timeout_seconds=30,
        max_attempts=max_attempts,
    )


def test_claim_generation_increments_across_requeue_and_reclaim(tmp_path: Path) -> None:
    store = FencedSQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    store.create_task(_spec("task-1", tmp_path))

    first = store.claim_next_lease("worker-a")
    assert first is not None
    assert first.generation == 1
    running = store.start_task_fenced(
        first.task.task_id,
        "worker-a",
        expected_version=first.task.version,
        lease_generation=first.generation,
    )
    queued = store.requeue_task_fenced(
        running.task_id,
        "worker-a",
        expected_version=running.version,
        lease_generation=first.generation,
        reason="retry",
    )
    assert queued.status is TaskStatus.QUEUED

    second = store.claim_next_lease("worker-a")
    assert second is not None
    assert second.generation == 2
    assert store.current_lease_generation("task-1") == 2


def test_old_generation_is_rejected_even_when_worker_id_is_reused(tmp_path: Path) -> None:
    store = FencedSQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    store.create_task(_spec("task-1", tmp_path))

    first = store.claim_next_lease("same-worker")
    assert first is not None
    running = store.start_task_fenced(
        "task-1",
        "same-worker",
        expected_version=first.task.version,
        lease_generation=first.generation,
    )
    store.requeue_task_fenced(
        "task-1",
        "same-worker",
        expected_version=running.version,
        lease_generation=first.generation,
        reason="retry",
    )
    second = store.claim_next_lease("same-worker")
    assert second is not None
    assert second.generation == first.generation + 1

    with pytest.raises(TaskLeaseError, match="stale lease generation"):
        store.start_task_fenced(
            "task-1",
            "same-worker",
            expected_version=second.task.version,
            lease_generation=first.generation,
        )

    running2 = store.start_task_fenced(
        "task-1",
        "same-worker",
        expected_version=second.task.version,
        lease_generation=second.generation,
    )
    with pytest.raises(TaskLeaseError, match="stale lease generation"):
        store.heartbeat_fenced(
            "task-1",
            "same-worker",
            expected_version=running2.version,
            lease_generation=first.generation,
        )
    with pytest.raises(TaskLeaseError, match="stale lease generation"):
        store.mark_side_effect_state_fenced(
            "task-1",
            "same-worker",
            expected_version=running2.version,
            lease_generation=first.generation,
            state="safe",
        )
    with pytest.raises(TaskLeaseError, match="stale lease generation"):
        store.complete_task_fenced(
            "task-1",
            "same-worker",
            expected_version=running2.version,
            lease_generation=first.generation,
            result=TaskExecutionResult(TaskStatus.SUCCEEDED),
        )
    with pytest.raises(TaskLeaseError, match="stale lease generation"):
        store.requeue_task_fenced(
            "task-1",
            "same-worker",
            expected_version=running2.version,
            lease_generation=first.generation,
            reason="stale",
        )

    terminal = store.complete_task_fenced(
        "task-1",
        "same-worker",
        expected_version=running2.version,
        lease_generation=second.generation,
        result=TaskExecutionResult(TaskStatus.SUCCEEDED),
    )
    assert terminal.status is TaskStatus.SUCCEEDED


def test_expired_lease_recovery_preserves_monotonic_fence(tmp_path: Path) -> None:
    now = [100.0]
    store = FencedSQLiteDurableTaskStore(
        tmp_path / "tasks.sqlite3", clock=lambda: now[0]
    )
    store.create_task(_spec("task-1", tmp_path))
    first = store.claim_next_lease("worker-a", lease_seconds=5)
    assert first is not None and first.generation == 1

    now[0] = 106.0
    recovered = store.recover_expired_leases()
    assert recovered[0].status is TaskStatus.QUEUED

    second = store.claim_next_lease("worker-b", lease_seconds=5)
    assert second is not None
    assert second.generation == 2
    with pytest.raises(TaskLeaseError, match="stale lease generation"):
        store.start_task_fenced(
            "task-1",
            "worker-b",
            expected_version=second.task.version,
            lease_generation=first.generation,
        )


def test_claim_event_records_fencing_generation(tmp_path: Path) -> None:
    store = FencedSQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    store.create_task(_spec("task-1", tmp_path))
    lease = store.claim_next_lease("worker-a")
    assert lease is not None

    events = store.list_events("task-1")
    claimed = [event for event in events if event.event_type == "task.claimed"][-1]
    assert claimed.payload["lease_generation"] == lease.generation


def _claim_worker(
    database: str,
    workspace: str,
    worker_id: str,
    output_queue,
) -> None:
    store = FencedSQLiteDurableTaskStore(database)
    claimed: list[tuple[str, int, str]] = []
    while True:
        lease = store.claim_next_lease(worker_id, lease_seconds=60)
        if lease is None:
            break
        claimed.append((lease.task.task_id, lease.generation, worker_id))
    output_queue.put(claimed)


@pytest.mark.skipif(not hasattr(mp, "get_context"), reason="multiprocessing unavailable")
def test_multi_process_claim_contention_claims_each_task_once_per_generation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite3"
    store = FencedSQLiteDurableTaskStore(database)
    task_ids = [f"task-{index:02d}" for index in range(24)]
    for task_id in task_ids:
        store.create_task(_spec(task_id, tmp_path))

    context = mp.get_context("spawn")
    output_queue = context.Queue()
    processes = [
        context.Process(
            target=_claim_worker,
            args=(str(database), str(tmp_path), f"worker-{index}", output_queue),
        )
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    claimed: list[tuple[str, int, str]] = []
    for _ in processes:
        try:
            claimed.extend(output_queue.get(timeout=5))
        except queue.Empty as exc:
            raise AssertionError("worker did not return claim evidence") from exc

    assert len(claimed) == len(task_ids)
    assert {task_id for task_id, _, _ in claimed} == set(task_ids)
    assert len({(task_id, generation) for task_id, generation, _ in claimed}) == len(task_ids)
    assert {generation for _, generation, _ in claimed} == {1}
