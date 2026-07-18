from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.message_bus import (
    AgentMessageBus,
    MessageBusCapacityError,
    MessageDraft,
    SQLiteMessageBusStore,
)


def test_agent_message_bus_is_public() -> None:
    assert AgentMessageBus.__name__ == "AgentMessageBus"


def test_draft_and_envelope_detach_and_deep_freeze_caller_data(tmp_path: Path) -> None:
    payload = {"nested": {"items": [1, 2]}, "state": "ready"}
    headers = {"trace": {"labels": ["a"]}}
    draft = MessageDraft(
        topic="agent.events",
        sender_id="agent-a",
        idempotency_key="immutable-1",
        payload=payload,
        headers=headers,
    )

    payload["state"] = "changed"
    payload["nested"]["items"].append(3)  # type: ignore[index,union-attr]
    payload["nested"]["api_key"] = "late-secret"  # type: ignore[index]
    headers["trace"]["labels"].append("b")  # type: ignore[index,union-attr]

    assert draft.canonical_dict()["payload"] == {
        "nested": {"items": [1, 2]},
        "state": "ready",
    }
    assert draft.canonical_dict()["headers"] == {"trace": {"labels": ["a"]}}

    store = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    result = store.publish(draft)
    assert result.message.to_dict()["payload"]["state"] == "ready"
    with pytest.raises(TypeError):
        result.message.payload["state"] = "mutate"  # type: ignore[index]


def test_payload_and_header_byte_limits_fail_before_insert(tmp_path: Path) -> None:
    store = SQLiteMessageBusStore(
        tmp_path / "bus.sqlite3",
        max_payload_bytes=40,
        max_headers_bytes=30,
        max_draft_bytes=512,
    )
    with pytest.raises(MessageBusCapacityError, match="payload"):
        store.publish(
            MessageDraft(
                topic="agent.events",
                sender_id="agent-a",
                idempotency_key="large-payload",
                payload={"blob": "x" * 100},
            )
        )
    with pytest.raises(MessageBusCapacityError, match="headers"):
        store.publish(
            MessageDraft(
                topic="agent.events",
                sender_id="agent-a",
                idempotency_key="large-headers",
                payload={},
                headers={"blob": "x" * 100},
            )
        )
    assert store.count_topic("agent.events") == 0


def test_capacity_rejection_audit_survives_business_exception(tmp_path: Path) -> None:
    store = SQLiteMessageBusStore(
        tmp_path / "bus.sqlite3", max_messages_per_topic=1
    )
    first = MessageDraft(
        topic="agent.events",
        sender_id="agent-a",
        idempotency_key="first",
        payload={"value": 1},
    )
    store.publish(first)

    with pytest.raises(MessageBusCapacityError):
        store.publish(
            MessageDraft(
                topic="agent.events",
                sender_id="agent-a",
                idempotency_key="second",
                payload={"value": 2},
            )
        )

    events = store.list_events(topic="agent.events")
    rejected = [
        event for event in events
        if event.event_type == "message.publish_rejected_capacity"
    ]
    assert len(rejected) == 1
    assert rejected[0].metadata["retained_count"] == 1

    retry = store.publish(first)
    assert retry.created is False
    assert store.count_topic("agent.events") == 1
