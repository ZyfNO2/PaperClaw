from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
import queue

import pytest

from paperclaw.message_bus import (
    MessageBusAckError,
    MessageBusCapacityError,
    MessageBusConflictError,
    MessageDraft,
    SQLiteMessageBusStore,
)


def _draft(
    key: str,
    *,
    topic: str = "agent.events",
    sender: str = "agent-a",
    recipient: str | None = None,
    value: object = 1,
) -> MessageDraft:
    return MessageDraft(
        topic=topic,
        sender_id=sender,
        recipient_id=recipient,
        idempotency_key=key,
        payload={"value": value},
        headers={"kind": "test"},
    )


def test_publish_sequence_and_idempotency(tmp_path: Path) -> None:
    store = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")

    first = store.publish(_draft("key-1"))
    second = store.publish(_draft("key-2"))
    retry = store.publish(_draft("key-1"))

    assert first.created is True
    assert first.message.sequence == 1
    assert second.message.sequence == 2
    assert retry.created is False
    assert retry.message == first.message
    assert store.latest_sequence("agent.events") == 2
    assert store.count_topic("agent.events") == 2

    event_types = [event.event_type for event in store.list_events(topic="agent.events")]
    assert "message.published" in event_types
    assert "message.publish_deduplicated" in event_types


def test_idempotency_key_conflict_is_rejected(tmp_path: Path) -> None:
    store = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    store.publish(_draft("same-key", value=1))

    with pytest.raises(MessageBusConflictError):
        store.publish(_draft("same-key", value=2))

    assert store.count_topic("agent.events") == 1
    assert store.latest_sequence("agent.events") == 1


def test_broadcast_and_direct_routing_are_consumer_isolated(tmp_path: Path) -> None:
    store = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    broadcast = store.publish(_draft("b", value="broadcast")).message
    direct_a = store.publish(_draft("a", recipient="consumer-a", value="a")).message
    direct_b = store.publish(_draft("c", recipient="consumer-b", value="b")).message

    messages_a = store.pull("consumer-a", "agent.events")
    messages_b = store.pull("consumer-b", "agent.events")
    messages_c = store.pull("consumer-c", "agent.events")

    assert [message.sequence for message in messages_a] == [broadcast.sequence, direct_a.sequence]
    assert [message.sequence for message in messages_b] == [broadcast.sequence, direct_b.sequence]
    assert [message.sequence for message in messages_c] == [broadcast.sequence]


def test_consumer_cursors_are_independent_and_ack_is_monotonic(tmp_path: Path) -> None:
    store = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    first = store.publish(_draft("1")).message
    second = store.publish(_draft("2")).message
    third = store.publish(_draft("3")).message

    cursor_a = store.ack("consumer-a", "agent.events", second.sequence)
    assert cursor_a.ack_sequence == second.sequence
    assert [m.sequence for m in store.pull("consumer-a", "agent.events")] == [third.sequence]

    # Another consumer retains its own cursor and still sees all broadcasts.
    assert [m.sequence for m in store.pull("consumer-b", "agent.events")] == [
        first.sequence,
        second.sequence,
        third.sequence,
    ]

    repeated = store.ack("consumer-a", "agent.events", first.sequence)
    assert repeated.ack_sequence == second.sequence
    repeated_same = store.ack("consumer-a", "agent.events", second.sequence)
    assert repeated_same.ack_sequence == second.sequence


def test_ack_cannot_advance_to_message_for_another_recipient(tmp_path: Path) -> None:
    store = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    direct = store.publish(
        _draft("private", recipient="consumer-b", value="private")
    ).message

    with pytest.raises(MessageBusAckError):
        store.ack("consumer-a", "agent.events", direct.sequence)

    assert store.get_cursor("consumer-a", "agent.events").ack_sequence == 0


def test_capacity_rejects_without_eviction_and_idempotent_retry_still_works(
    tmp_path: Path,
) -> None:
    store = SQLiteMessageBusStore(
        tmp_path / "bus.sqlite3", max_messages_per_topic=2
    )
    first = store.publish(_draft("1"))
    store.publish(_draft("2"))

    with pytest.raises(MessageBusCapacityError):
        store.publish(_draft("3"))

    retry = store.publish(_draft("1"))
    assert retry.created is False
    assert retry.message == first.message
    assert store.count_topic("agent.events") == 2
    assert store.latest_sequence("agent.events") == 2


def test_envelope_rejects_nested_credential_fields_but_allows_token_accounting() -> None:
    with pytest.raises(ValueError, match="credential-shaped"):
        MessageDraft(
            topic="agent.events",
            sender_id="agent-a",
            idempotency_key="secret-message",
            payload={"nested": {"api_key": "must-not-persist"}},
        )

    with pytest.raises(ValueError, match="credential-shaped"):
        MessageDraft(
            topic="agent.events",
            sender_id="agent-a",
            idempotency_key="secret-header",
            payload={},
            headers={"auth": {"client-secret": "must-not-persist"}},
        )

    draft = MessageDraft(
        topic="agent.events",
        sender_id="agent-a",
        idempotency_key="metrics",
        payload={"token_budget": 4096, "input_tokens": 120},
    )
    assert draft.payload["token_budget"] == 4096


def _publisher_process(
    database: str,
    process_index: int,
    messages_per_process: int,
    output_queue,
) -> None:
    store = SQLiteMessageBusStore(database, max_messages_per_topic=10_000)
    published: list[tuple[str, int]] = []
    for index in range(messages_per_process):
        key = f"p{process_index}-m{index}"
        result = store.publish(
            MessageDraft(
                topic="agent.concurrent",
                sender_id=f"publisher-{process_index}",
                idempotency_key=key,
                payload={"publisher": process_index, "index": index},
            )
        )
        published.append((result.message.message_id, result.message.sequence))
    output_queue.put(published)


@pytest.mark.skipif(not hasattr(mp, "get_context"), reason="multiprocessing unavailable")
def test_multi_process_publishers_allocate_unique_contiguous_topic_sequences(
    tmp_path: Path,
) -> None:
    database = tmp_path / "bus.sqlite3"
    SQLiteMessageBusStore(database, max_messages_per_topic=10_000)

    process_count = 4
    messages_per_process = 20
    expected = process_count * messages_per_process
    context = mp.get_context("spawn")
    output_queue = context.Queue()
    processes = [
        context.Process(
            target=_publisher_process,
            args=(str(database), process_index, messages_per_process, output_queue),
        )
        for process_index in range(process_count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=45)
        assert process.exitcode == 0

    published: list[tuple[str, int]] = []
    for _ in processes:
        try:
            published.extend(output_queue.get(timeout=5))
        except queue.Empty as exc:
            raise AssertionError("publisher did not return evidence") from exc

    assert len(published) == expected
    assert len({message_id for message_id, _ in published}) == expected
    sequences = sorted(sequence for _, sequence in published)
    assert sequences == list(range(1, expected + 1))

    store = SQLiteMessageBusStore(database, max_messages_per_topic=10_000)
    assert store.count_topic("agent.concurrent") == expected
    assert store.latest_sequence("agent.concurrent") == expected
