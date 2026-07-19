from __future__ import annotations

from pathlib import Path

from paperclaw.message_bus import AgentMessageBus, SQLiteMessageBusStore


def test_agent_bus_send_receive_ack_roundtrip(tmp_path: Path) -> None:
    bus = AgentMessageBus(SQLiteMessageBusStore(tmp_path / "bus.sqlite3"))

    sent = bus.send(
        sender_id="agent-a",
        recipient_id="agent-b",
        topic="agent.control",
        idempotency_key="handoff-1",
        payload={"action": "review", "artifact_id": "artifact-1"},
    )

    assert sent.created is True
    assert bus.receive("agent-c", "agent.control") == ()
    received = bus.receive("agent-b", "agent.control")
    assert received == (sent.message,)

    cursor = bus.ack("agent-b", "agent.control", sent.message.sequence)
    assert cursor.ack_sequence == sent.message.sequence
    assert bus.receive("agent-b", "agent.control") == ()
    assert bus.cursor("agent-b", "agent.control") == cursor


def test_agent_bus_idempotent_send_returns_existing_message(tmp_path: Path) -> None:
    bus = AgentMessageBus(SQLiteMessageBusStore(tmp_path / "bus.sqlite3"))

    first = bus.send(
        sender_id="agent-a",
        topic="agent.events",
        idempotency_key="event-1",
        payload={"state": "ready"},
    )
    retry = bus.send(
        sender_id="agent-a",
        topic="agent.events",
        idempotency_key="event-1",
        payload={"state": "ready"},
    )

    assert first.created is True
    assert retry.created is False
    assert retry.message == first.message
