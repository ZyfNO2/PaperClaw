"""Agent-facing façade over the durable MessageBusStore contract."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import ConsumerCursor, MessageDraft, MessageEnvelope, PublishResult
from .store import MessageBusStore


class AgentMessageBus:
    """Small stable API for Agent send/receive/ack workflows."""

    def __init__(self, store: MessageBusStore) -> None:
        self.store = store

    def send(
        self,
        *,
        sender_id: str,
        topic: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
        recipient_id: str | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> PublishResult:
        return self.store.publish(
            MessageDraft(
                topic=topic,
                sender_id=sender_id,
                recipient_id=recipient_id,
                idempotency_key=idempotency_key,
                payload=payload,
                headers=headers or {},
            )
        )

    def receive(
        self,
        agent_id: str,
        topic: str,
        *,
        limit: int = 50,
    ) -> tuple[MessageEnvelope, ...]:
        return self.store.pull(agent_id, topic, limit=limit)

    def ack(self, agent_id: str, topic: str, sequence: int) -> ConsumerCursor:
        return self.store.ack(agent_id, topic, sequence)

    def cursor(self, agent_id: str, topic: str) -> ConsumerCursor:
        return self.store.get_cursor(agent_id, topic)


__all__ = ["AgentMessageBus"]
