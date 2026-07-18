from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.tasks.contracts import TaskLeaseError, TaskSpec
from paperclaw.tasks.strict_store import StrictFencedSQLiteDurableTaskStore


def test_production_store_disables_unfenced_owner_api(tmp_path: Path) -> None:
    store = StrictFencedSQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    store.create_task(
        TaskSpec(
            task_id="task-1",
            objective="test strict fencing",
            workspace=str(tmp_path),
            max_steps=2,
            timeout_seconds=30,
            max_attempts=2,
        )
    )

    for call in (
        lambda: store.claim_next("worker"),
        lambda: store.start_task("task-1", "worker", expected_version=0),
        lambda: store.heartbeat("task-1", "worker", expected_version=0),
        lambda: store.mark_side_effect_state(
            "task-1", "worker", expected_version=0, state="safe"
        ),
        lambda: store.complete_task(
            "task-1", "worker", expected_version=0, result=None
        ),
        lambda: store.requeue_task(
            "task-1", "worker", expected_version=0, reason="retry"
        ),
    ):
        with pytest.raises(TaskLeaseError, match="unfenced"):
            call()

    lease = store.claim_next_lease("worker")
    assert lease is not None
    assert lease.generation == 1
