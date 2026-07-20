from __future__ import annotations

import multiprocessing
import os
import time
from uuid import uuid4

import pytest

from paperclaw.message_bus import (
    MessageBusConflictError,
    MessageDraft,
    RedisStreamsMessageBusStore,
)
from paperclaw.multiagent.bus_runtime import (
    TEAM_EVENT_TOPIC,
    TEAM_REQUEST_TOPIC,
    TeamRunRequest,
)
from paperclaw.multiagent.contracts import AgentTask, TeamBudget, TeamStopReason
from paperclaw.multiagent.coordinator import CoordinatorResult
from paperclaw.multiagent.postgres_store import (
    PostgreSQLResilientChoreographyStore,
)
from paperclaw.multiagent.resilient_runtime import (
    ResilientBusDrivenTeamRuntime,
    TerminalSnapshot,
)

pytestmark = pytest.mark.distributed


class ProcessCoordinator:
    def run(self, user_goal, tasks):
        return CoordinatorResult(
            stop_reason=TeamStopReason.ALL_TASKS_COMPLETED,
            summary="distributed complete",
        )

    def cancel(self, task_id, tasks):
        return None


def _request(request_id: str) -> TeamRunRequest:
    return TeamRunRequest(
        request_id=request_id,
        user_goal="complete one distributed request",
        tasks=(
            AgentTask(
                task_id="check",
                title="check",
                objective="complete",
                acceptance_criteria=["complete"],
                allowed_paths=["."],
                allowed_tools=[],
                max_steps=1,
            ),
        ),
        budget=TeamBudget(
            max_agents=1,
            max_total_steps=1,
            max_total_model_calls=1,
            max_fix_rounds=0,
        ),
    )


def _worker_main(redis_url, postgres_dsn, namespace, schema, output):
    bus = RedisStreamsMessageBusStore(
        redis_url,
        namespace=namespace,
        claim_idle_ms=5_000,
        block_ms=20,
    )
    state = PostgreSQLResilientChoreographyStore(postgres_dsn, schema=schema)
    runtime = ResilientBusDrivenTeamRuntime(
        bus,
        state,
        lambda *_args: ProcessCoordinator(),
        consumer_id="distributed-runtime",
    )
    idle = 0
    while idle < 8:
        outcomes = runtime.run_once(limit=1)
        if not outcomes:
            idle += 1
            time.sleep(0.02)
            continue
        idle = 0
        for outcome in outcomes:
            if outcome.terminal and outcome.acknowledged:
                output.put(outcome.request_id)


@pytest.fixture
def distributed_services():
    redis_url = os.environ.get("PAPERCLAW_TEST_REDIS_URL", "redis://localhost:6379/15")
    postgres_dsn = os.environ.get(
        "PAPERCLAW_TEST_POSTGRES_DSN",
        "postgresql://paperclaw:paperclaw@localhost:5432/paperclaw",
    )
    token = uuid4().hex[:12]
    namespace = f"paperclaw-test-{token}"
    schema = f"paperclaw_test_{token}"
    try:
        import redis
        import psycopg

        redis.Redis.from_url(redis_url).ping()
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute("SELECT 1")
    except Exception as exc:
        pytest.skip(f"distributed services unavailable: {exc}")
    yield redis_url, postgres_dsn, namespace, schema
    client = redis.Redis.from_url(redis_url)
    for key in client.scan_iter(f"{namespace}:*"):
        client.delete(key)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_redis_streams_preserves_idempotency_scope_and_contiguous_ack(
    distributed_services,
):
    redis_url, _, namespace, _ = distributed_services
    bus = RedisStreamsMessageBusStore(
        redis_url,
        namespace=namespace,
        claim_idle_ms=50,
        block_ms=5,
    )
    first = bus.publish(
        MessageDraft(
            topic="test.requests",
            sender_id="sender-a",
            idempotency_key="same-key",
            payload={"value": 1},
        )
    )
    duplicate = bus.publish(
        MessageDraft(
            topic="test.requests",
            sender_id="sender-a",
            idempotency_key="same-key",
            payload={"value": 1},
        )
    )
    other_sender = bus.publish(
        MessageDraft(
            topic="test.requests",
            sender_id="sender-b",
            idempotency_key="same-key",
            payload={"value": 1},
        )
    )

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.message.message_id == first.message.message_id
    assert other_sender.created is True
    assert other_sender.message.sequence == first.message.sequence + 1
    with pytest.raises(MessageBusConflictError):
        bus.publish(
            MessageDraft(
                topic="test.requests",
                sender_id="sender-a",
                idempotency_key="same-key",
                payload={"value": 2},
            )
        )

    messages = bus.pull("consumer-a", "test.requests", limit=10)
    assert [item.sequence for item in messages] == [1, 2]
    cursor = bus.ack("consumer-a", "test.requests", 2)
    assert cursor.ack_sequence == 0
    cursor = bus.ack("consumer-a", "test.requests", 1)
    assert cursor.ack_sequence == 2


def test_redis_pending_entry_is_claimed_after_worker_death(distributed_services):
    redis_url, _, namespace, _ = distributed_services
    producer = RedisStreamsMessageBusStore(
        redis_url,
        namespace=namespace,
        claim_idle_ms=50,
        block_ms=5,
    )
    producer.publish(
        MessageDraft(
            topic="test.claim",
            sender_id="sender",
            idempotency_key="claim-1",
            payload={"value": 1},
        )
    )
    first_worker = RedisStreamsMessageBusStore(
        redis_url,
        namespace=namespace,
        claim_idle_ms=50,
        block_ms=5,
    )
    claimed = first_worker.pull("shared-consumer", "test.claim", limit=1)
    assert len(claimed) == 1

    time.sleep(0.08)
    second_worker = RedisStreamsMessageBusStore(
        redis_url,
        namespace=namespace,
        claim_idle_ms=50,
        block_ms=5,
    )
    recovered = second_worker.pull("shared-consumer", "test.claim", limit=1)
    assert [item.message_id for item in recovered] == [claimed[0].message_id]
    assert second_worker.ack(
        "shared-consumer", "test.claim", recovered[0].sequence
    ).ack_sequence == recovered[0].sequence


def test_postgres_terminal_and_outbox_are_atomic_and_ordered(distributed_services):
    _, postgres_dsn, _, schema = distributed_services
    store = PostgreSQLResilientChoreographyStore(postgres_dsn, schema=schema)
    state = store.begin_attempt("runtime", "message-1")
    snapshot = TerminalSnapshot(
        request_id="request-1",
        request_message_id="message-1",
        request_sequence=1,
        attempt=state.attempts,
        failure_category=None,
        failure_disposition=None,
        dead_lettered=False,
        metrics={"succeeded": True},
    )
    store.commit_terminal(
        "runtime",
        "message-1",
        snapshot,
        (
            MessageDraft(
                topic=TEAM_EVENT_TOPIC,
                sender_id="runtime",
                idempotency_key="metrics",
                payload={"event_type": "team.run.metrics"},
            ),
            MessageDraft(
                topic=TEAM_EVENT_TOPIC,
                sender_id="runtime",
                idempotency_key="terminal",
                payload={"event_type": "team.run.terminal"},
            ),
        ),
    )

    assert store.get_attempt("runtime", "message-1").terminal is True
    assert store.get_terminal("runtime", "message-1") == snapshot
    pending = store.pending_outbox("runtime", "message-1")
    assert [item.payload["event_type"] for item in pending] == [
        "team.run.metrics",
        "team.run.terminal",
    ]
    first_claim = store.claim_pending_outbox(worker_id="worker-a", limit=1)
    second_claim = store.claim_pending_outbox(worker_id="worker-b", limit=1)
    assert len(first_claim) == len(second_claim) == 1
    assert first_claim[0].outbox_id != second_claim[0].outbox_id


def test_two_processes_share_redis_group_and_postgres_state_without_duplicates(
    distributed_services,
):
    redis_url, postgres_dsn, namespace, schema = distributed_services
    bus = RedisStreamsMessageBusStore(redis_url, namespace=namespace, block_ms=5)
    state = PostgreSQLResilientChoreographyStore(postgres_dsn, schema=schema)
    runtime = ResilientBusDrivenTeamRuntime(
        bus,
        state,
        lambda *_args: ProcessCoordinator(),
        consumer_id="distributed-runtime",
    )
    request_ids = [f"distributed-{index}" for index in range(8)]
    for request_id in request_ids:
        runtime.submit(_request(request_id))

    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    processes = [
        context.Process(
            target=_worker_main,
            args=(redis_url, postgres_dsn, namespace, schema, output),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    completed = [output.get(timeout=2) for _ in request_ids]
    assert sorted(completed) == sorted(request_ids)
    assert len(completed) == len(set(completed))
    assert bus.get_cursor("distributed-runtime", TEAM_REQUEST_TOPIC).ack_sequence == len(
        request_ids
    )
    terminal_events = [
        message
        for message in bus.pull("audit", TEAM_EVENT_TOPIC, limit=1000)
        if message.payload.get("event_type") == "team.run.terminal"
    ]
    assert len(terminal_events) == len(request_ids)
