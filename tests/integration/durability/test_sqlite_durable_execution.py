from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from paperclaw.durability import (
    CompareAndSwapError,
    IdempotentActionExecutor,
    IdempotencyRecordConflictError,
    LeaseConflictError,
    RecoveryCoordinator,
    RecoveryPolicyRegistry,
    SQLiteDurableRunStore,
)


class FakeClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class RaisingPolicy:
    policy_id = "raising-v1"

    def classify(self, run, *, action_receipt_count):
        raise RuntimeError("policy exploded")


def build_store(tmp_path, clock=None):
    return SQLiteDurableRunStore(
        tmp_path / "durable.db",
        clock=clock or FakeClock(),
    )


def test_create_idempotency_metadata_sanitization_and_cas(tmp_path):
    store = build_store(tmp_path)
    run, created = store.create_run(
        "run-1",
        "digest-a",
        idempotency_key="idem-1",
        metadata={"api_key": "hidden", "purpose": "test"},
    )
    assert created is True
    assert run.state == "queued"
    assert run.metadata == {"purpose": "test"}

    duplicate, created = store.create_run(
        "different-public-id",
        "digest-a",
        idempotency_key="idem-1",
    )
    assert created is False
    assert duplicate.run_id == "run-1"

    with pytest.raises(IdempotencyRecordConflictError):
        store.create_run(
            "run-2",
            "digest-b",
            idempotency_key="idem-1",
        )

    running = store.claim_next("worker-a")
    assert running is not None
    completed = store.transition(
        running.run_id,
        expected_state="running",
        expected_version=running.version,
        next_state="completed",
        reason="done",
        actor="worker-a",
    )
    assert completed.terminal is True

    with pytest.raises(CompareAndSwapError):
        store.transition(
            running.run_id,
            expected_state="running",
            expected_version=running.version,
            next_state="failed",
            reason="stale",
            actor="worker-a",
        )

    transitions = store.transitions("run-1")
    assert [item.to_state for item in transitions] == [
        "queued",
        "running",
        "completed",
    ]


def test_two_workers_cannot_claim_the_same_run(tmp_path):
    store = build_store(tmp_path)
    store.create_run("run-claim", "digest")
    barrier = Barrier(2)

    def claim(worker_id):
        barrier.wait()
        result = store.claim_next(worker_id, lease_seconds=60)
        return result.run_id if result else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("worker-a", "worker-b")))

    assert sorted(result for result in results if result is not None) == [
        "run-claim"
    ]
    assert results.count(None) == 1


def test_lease_renewal_checks_owner_and_version(tmp_path):
    clock = FakeClock()
    store = build_store(tmp_path, clock)
    store.create_run("run-lease", "digest")
    run = store.claim_next("worker-a", lease_seconds=10)
    assert run is not None
    assert store.renew_lease(
        run.run_id,
        "worker-a",
        expected_run_version=run.version,
        lease_seconds=20,
    ) == clock.value + 20

    with pytest.raises(LeaseConflictError):
        store.renew_lease(
            run.run_id,
            "worker-b",
            expected_run_version=run.version,
        )
    with pytest.raises(LeaseConflictError):
        store.renew_lease(
            run.run_id,
            "worker-a",
            expected_run_version=run.version + 1,
        )


def test_recovery_requeues_once_then_requires_manual_review(tmp_path):
    clock = FakeClock()
    store = build_store(tmp_path, clock)
    store.create_run("run-recover", "digest")
    first_claim = store.claim_next("worker-a", lease_seconds=5)
    assert first_claim is not None

    clock.value += 6
    first = RecoveryCoordinator(store).reconcile()
    assert len(first) == 1
    assert first[0].next_state == "queued"
    requeued = store.get_run("run-recover")
    assert requeued.recovery_attempts == 1

    second_claim = store.claim_next("worker-b", lease_seconds=5)
    assert second_claim is not None
    clock.value += 6
    second = RecoveryCoordinator(store).reconcile()
    assert second[0].next_state == "recovery_required"
    assert store.get_run("run-recover").state == "recovery_required"

    assert RecoveryCoordinator(store).reconcile() == ()


def test_action_receipt_prevents_duplicate_side_effect(tmp_path):
    store = build_store(tmp_path)
    store.create_run("run-action", "digest")
    executor = IdempotentActionExecutor(store)
    calls = 0

    def side_effect():
        nonlocal calls
        calls += 1
        return {"written": True, "api_key": "not-persisted"}

    first = executor.execute(
        "run-action",
        "step-1",
        "file_write",
        {"path": "out.txt", "content": "ok"},
        side_effect,
    )
    second = executor.execute(
        "run-action",
        "step-1",
        "file_write",
        {"path": "out.txt", "content": "ok"},
        side_effect,
    )
    assert calls == 1
    assert first == {"written": True}
    assert second == first


def test_uncertain_action_and_plugin_failure_fail_closed(tmp_path):
    clock = FakeClock()
    store = build_store(tmp_path, clock)
    store.create_run("run-unsafe", "digest")
    running = store.claim_next("worker-a", lease_seconds=5)
    assert running is not None
    store.reserve_action(
        running.run_id,
        "step-1",
        "external_write",
        {"target": "remote"},
    )
    clock.value += 6
    result = RecoveryCoordinator(store).reconcile()
    assert result[0].next_state == "recovery_required"

    store.create_run("run-plugin", "digest")
    plugin_run = store.claim_next("worker-b", lease_seconds=5)
    assert plugin_run is not None
    clock.value += 6
    registry = RecoveryPolicyRegistry(
        [RaisingPolicy()], active_policy_id="raising-v1"
    )
    plugin_result = RecoveryCoordinator(store, policy=registry).reconcile()
    assert plugin_result[0].next_state == "recovery_required"
    assert registry.failures
