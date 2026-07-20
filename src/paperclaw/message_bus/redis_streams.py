"""Redis Streams implementation of the stable MessageBusStore protocol.

The adapter uses one Redis Stream per topic, one consumer group per logical
``consumer_id``, exact publish idempotency through a Lua transaction, pending
entry recovery through ``XAUTOCLAIM``, and a contiguous logical Ack cursor.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from .contracts import (
    ConsumerCursor,
    MessageBusAckError,
    MessageBusCapacityError,
    MessageBusConflictError,
    MessageBusEvent,
    MessageDraft,
    MessageEnvelope,
    PublishResult,
    canonical_draft_bytes,
    canonical_json_bytes,
    thaw_json,
)

_PUBLISH_SCRIPT = r"""
local existing = redis.call('HGET', KEYS[4], ARGV[1])
if existing then
  local decoded = cjson.decode(existing)
  if decoded['digest'] ~= ARGV[2] then
    return {'CONFLICT'}
  end
  local event_id = redis.call('INCR', KEYS[6])
  redis.call('XADD', KEYS[7], '*',
    'event_id', tostring(event_id),
    'event_type', 'message.publish_deduplicated',
    'topic', ARGV[3],
    'sequence', tostring(decoded['sequence']),
    'message_id', decoded['message_id'],
    'consumer_id', '',
    'metadata_json', ARGV[12],
    'created_at', ARGV[9])
  return {'EXISTING', decoded['stream_id'], tostring(decoded['sequence'])}
end

if redis.call('XLEN', KEYS[2]) >= tonumber(ARGV[10]) then
  local event_id = redis.call('INCR', KEYS[6])
  redis.call('XADD', KEYS[7], '*',
    'event_id', tostring(event_id),
    'event_type', 'message.publish_rejected_capacity',
    'topic', ARGV[3],
    'sequence', '',
    'message_id', '',
    'consumer_id', '',
    'metadata_json', ARGV[13],
    'created_at', ARGV[9])
  return {'CAPACITY'}
end

local sequence = redis.call('INCR', KEYS[1])
local stream_id = redis.call('XADD', KEYS[2], '*',
  'sequence', tostring(sequence),
  'sender_id', ARGV[4],
  'recipient_id', ARGV[5],
  'idempotency_key', ARGV[1],
  'digest', ARGV[2],
  'payload_json', ARGV[6],
  'headers_json', ARGV[7],
  'created_at', ARGV[9])
local message_id = 'msg-' .. string.gsub(stream_id, '-', '.')
redis.call('HSET', KEYS[3], tostring(sequence), stream_id)
redis.call('HSET', KEYS[4], ARGV[1], cjson.encode({
  digest=ARGV[2], stream_id=stream_id, sequence=sequence,
  message_id=message_id
}))
local event_id = redis.call('INCR', KEYS[6])
redis.call('XADD', KEYS[7], '*',
  'event_id', tostring(event_id),
  'event_type', 'message.published',
  'topic', ARGV[3],
  'sequence', tostring(sequence),
  'message_id', message_id,
  'consumer_id', '',
  'metadata_json', ARGV[11],
  'created_at', ARGV[9])
return {'CREATED', stream_id, tostring(sequence)}
"""

_ACK_SCRIPT = r"""
local stream_id = redis.call('HGET', KEYS[2], ARGV[3])
if not stream_id then
  return {'MISSING'}
end
local rows = redis.call('XRANGE', KEYS[1], stream_id, stream_id)
if #rows == 0 then
  return {'MISSING'}
end
local fields = rows[1][2]
local recipient = ''
for i=1,#fields,2 do
  if fields[i] == 'recipient_id' then recipient = fields[i+1] end
end
if recipient ~= '' and recipient ~= ARGV[1] then
  return {'INELIGIBLE'}
end
redis.call('XACK', KEYS[1], ARGV[2], stream_id)
redis.call('ZADD', KEYS[4], tonumber(ARGV[3]), ARGV[3])
local current = tonumber(redis.call('HGET', KEYS[3], ARGV[4]) or '0')
while redis.call('ZSCORE', KEYS[4], tostring(current + 1)) do
  redis.call('ZREM', KEYS[4], tostring(current + 1))
  current = current + 1
end
redis.call('HSET', KEYS[3], ARGV[4], tostring(current))
return {'OK', tostring(current)}
"""


class RedisStreamsMessageBusStore:
    """Multi-host Redis Streams backend for PaperClaw MessageBusStore."""

    def __init__(
        self,
        redis_url: str,
        *,
        namespace: str = "paperclaw",
        max_messages_per_topic: int = 10_000,
        max_payload_bytes: int = 1_048_576,
        max_headers_bytes: int = 65_536,
        max_draft_bytes: int = 1_310_720,
        claim_idle_ms: int = 1_000,
        block_ms: int = 50,
        clock: Callable[[], float] = time.time,
        client: Any | None = None,
    ) -> None:
        if not redis_url and client is None:
            raise ValueError("redis_url is required")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", namespace):
            raise ValueError("namespace must be a safe identifier")
        for name, value in (
            ("max_messages_per_topic", max_messages_per_topic),
            ("max_payload_bytes", max_payload_bytes),
            ("max_headers_bytes", max_headers_bytes),
            ("max_draft_bytes", max_draft_bytes),
            ("claim_idle_ms", claim_idle_ms),
            ("block_ms", block_ms),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if client is None:
            try:
                import redis
            except ImportError as exc:
                raise RuntimeError(
                    "Redis backend requires the 'distributed' optional dependency"
                ) from exc
            client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._redis = client
        self.namespace = namespace
        self.max_messages_per_topic = max_messages_per_topic
        self.max_payload_bytes = max_payload_bytes
        self.max_headers_bytes = max_headers_bytes
        self.max_draft_bytes = max_draft_bytes
        self.claim_idle_ms = claim_idle_ms
        self.block_ms = block_ms
        self._clock = clock
        self._instance_id = f"worker-{uuid4().hex[:16]}"
        self._publish_script = self._redis.register_script(_PUBLISH_SCRIPT)
        self._ack_script = self._redis.register_script(_ACK_SCRIPT)

    def publish(self, draft: MessageDraft) -> PublishResult:
        encoded = canonical_draft_bytes(draft)
        self._validate_sizes(draft, encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        topic_keys = self._topic_keys(draft.topic)
        metadata = {
            "sender_id": draft.sender_id,
            "recipient_id": draft.recipient_id,
        }
        result = self._publish_script(
            keys=[
                topic_keys["sequence"],
                topic_keys["stream"],
                topic_keys["index"],
                topic_keys["idempotency"],
                topic_keys["unused"],
                self._event_sequence_key,
                self._event_stream_key,
            ],
            args=[
                draft.idempotency_key,
                digest,
                draft.topic,
                draft.sender_id,
                draft.recipient_id or "",
                _json_dump(draft.payload),
                _json_dump(draft.headers),
                "",
                repr(float(self._clock())),
                self.max_messages_per_topic,
                _json_dump(metadata),
                _json_dump({"sender_id": draft.sender_id}),
                _json_dump({"retained_count": self.max_messages_per_topic}),
            ],
        )
        status = _text(result[0])
        if status == "CONFLICT":
            raise MessageBusConflictError(
                "idempotency key is already bound to a different message"
            )
        if status == "CAPACITY":
            raise MessageBusCapacityError(
                "topic retained-message capacity is exhausted"
            )
        stream_id = _text(result[1])
        envelope = self._read_stream_message(draft.topic, stream_id)
        return PublishResult(envelope, status == "CREATED")

    def pull(
        self,
        consumer_id: str,
        topic: str,
        *,
        limit: int = 50,
    ) -> tuple[MessageEnvelope, ...]:
        _validate_identifier(consumer_id, "consumer_id")
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be in [1, 1000]")
        keys = self._topic_keys(topic)
        group = self._group_name(consumer_id)
        self._ensure_group(keys["stream"], group)
        delivered: list[tuple[str, Mapping[str, str]]] = []
        try:
            claimed = self._redis.xautoclaim(
                keys["stream"],
                group,
                self._instance_id,
                self.claim_idle_ms,
                "0-0",
                count=limit,
            )
            if claimed and len(claimed) >= 2:
                delivered.extend(claimed[1])
        except Exception as exc:
            if "unknown command" not in str(exc).lower():
                raise
        remaining = max(0, limit - len(delivered))
        if remaining:
            rows = self._redis.xreadgroup(
                group,
                self._instance_id,
                {keys["stream"]: ">"},
                count=remaining,
                block=self.block_ms,
            )
            for _, messages in rows or ():
                delivered.extend(messages)

        envelopes: list[MessageEnvelope] = []
        seen: set[str] = set()
        for stream_id, fields in delivered:
            stream_id = _text(stream_id)
            if stream_id in seen:
                continue
            seen.add(stream_id)
            envelope = self._envelope(topic, stream_id, fields)
            if envelope.recipient_id not in {None, consumer_id}:
                self._ack_ineligible(consumer_id, topic, envelope.sequence, group)
                continue
            envelopes.append(envelope)
            if len(envelopes) >= limit:
                break
        return tuple(sorted(envelopes, key=lambda item: item.sequence))

    def ack(self, consumer_id: str, topic: str, sequence: int) -> ConsumerCursor:
        _validate_identifier(consumer_id, "consumer_id")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        current = self.get_cursor(consumer_id, topic)
        if sequence <= current.ack_sequence:
            return current
        keys = self._topic_keys(topic)
        group = self._group_name(consumer_id)
        self._ensure_group(keys["stream"], group)
        result = self._ack_script(
            keys=[
                keys["stream"],
                keys["index"],
                self._cursor_hash_key,
                self._acked_set_key(consumer_id, topic),
            ],
            args=[
                consumer_id,
                group,
                sequence,
                self._cursor_field(consumer_id, topic),
            ],
        )
        status = _text(result[0])
        if status != "OK":
            raise MessageBusAckError(
                "ack sequence is not an eligible message for this consumer"
            )
        cursor = ConsumerCursor(
            consumer_id,
            topic,
            int(_text(result[1])),
            float(self._clock()),
        )
        self._append_event(
            "message.cursor_acknowledged",
            topic,
            sequence=sequence,
            consumer_id=consumer_id,
        )
        return cursor

    def get_cursor(self, consumer_id: str, topic: str) -> ConsumerCursor:
        _validate_identifier(consumer_id, "consumer_id")
        raw = self._redis.hget(
            self._cursor_hash_key,
            self._cursor_field(consumer_id, topic),
        )
        return ConsumerCursor(
            consumer_id,
            topic,
            int(_text(raw)) if raw is not None else 0,
            None,
        )

    def list_events(
        self,
        *,
        topic: str | None = None,
        after_event_id: int = 0,
        limit: int = 500,
    ) -> tuple[MessageBusEvent, ...]:
        if after_event_id < 0 or not 1 <= limit <= 5_000:
            raise ValueError("invalid event query bounds")
        rows = self._redis.xrange(self._event_stream_key, "-", "+", count=limit * 4)
        events: list[MessageBusEvent] = []
        for _, raw_fields in rows:
            fields = {_text(key): _text(value) for key, value in raw_fields.items()}
            event_id = int(fields["event_id"])
            if event_id <= after_event_id:
                continue
            if topic is not None and fields["topic"] != topic:
                continue
            events.append(
                MessageBusEvent(
                    event_id=event_id,
                    event_type=fields["event_type"],
                    topic=fields["topic"],
                    sequence=int(fields["sequence"]) if fields.get("sequence") else None,
                    message_id=fields.get("message_id") or None,
                    consumer_id=fields.get("consumer_id") or None,
                    metadata=json.loads(fields.get("metadata_json") or "{}"),
                    created_at=float(fields["created_at"]),
                )
            )
            if len(events) >= limit:
                break
        return tuple(events)

    def count_topic(self, topic: str) -> int:
        return int(self._redis.xlen(self._topic_keys(topic)["stream"]))

    def latest_sequence(self, topic: str) -> int:
        raw = self._redis.get(self._topic_keys(topic)["sequence"])
        return int(_text(raw)) if raw is not None else 0

    def _read_stream_message(self, topic: str, stream_id: str) -> MessageEnvelope:
        rows = self._redis.xrange(
            self._topic_keys(topic)["stream"],
            stream_id,
            stream_id,
        )
        if not rows:
            raise RuntimeError("published Redis Stream message is missing")
        _, fields = rows[0]
        return self._envelope(topic, stream_id, fields)

    def _envelope(
        self,
        topic: str,
        stream_id: str,
        raw_fields: Mapping[Any, Any],
    ) -> MessageEnvelope:
        fields = {_text(key): _text(value) for key, value in raw_fields.items()}
        return MessageEnvelope(
            message_id=f"msg-{stream_id.replace('-', '.')}",
            topic=topic,
            sequence=int(fields["sequence"]),
            sender_id=fields["sender_id"],
            recipient_id=fields.get("recipient_id") or None,
            idempotency_key=fields["idempotency_key"],
            payload=json.loads(fields["payload_json"]),
            headers=json.loads(fields["headers_json"]),
            created_at=float(fields["created_at"]),
        )

    def _ack_ineligible(
        self,
        consumer_id: str,
        topic: str,
        sequence: int,
        group: str,
    ) -> None:
        keys = self._topic_keys(topic)
        stream_id = self._redis.hget(keys["index"], sequence)
        if stream_id is not None:
            self._redis.xack(keys["stream"], group, stream_id)
            self._redis.zadd(self._acked_set_key(consumer_id, topic), {str(sequence): sequence})
            self._advance_cursor(consumer_id, topic)

    def _advance_cursor(self, consumer_id: str, topic: str) -> None:
        field = self._cursor_field(consumer_id, topic)
        cursor = int(_text(self._redis.hget(self._cursor_hash_key, field) or 0))
        acked = self._acked_set_key(consumer_id, topic)
        pipeline = self._redis.pipeline()
        while self._redis.zscore(acked, str(cursor + 1)) is not None:
            cursor += 1
            pipeline.zrem(acked, str(cursor))
        pipeline.hset(self._cursor_hash_key, field, cursor)
        pipeline.execute()

    def _ensure_group(self, stream: str, group: str) -> None:
        try:
            self._redis.xgroup_create(stream, group, id="0-0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def _append_event(
        self,
        event_type: str,
        topic: str,
        *,
        sequence: int | None = None,
        message_id: str | None = None,
        consumer_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        event_id = int(self._redis.incr(self._event_sequence_key))
        self._redis.xadd(
            self._event_stream_key,
            {
                "event_id": event_id,
                "event_type": event_type,
                "topic": topic,
                "sequence": "" if sequence is None else sequence,
                "message_id": message_id or "",
                "consumer_id": consumer_id or "",
                "metadata_json": _json_dump(metadata or {}),
                "created_at": repr(float(self._clock())),
            },
        )

    def _validate_sizes(self, draft: MessageDraft, encoded: bytes) -> None:
        if len(canonical_json_bytes(draft.payload)) > self.max_payload_bytes:
            raise MessageBusCapacityError("message payload exceeds configured bytes")
        if len(canonical_json_bytes(draft.headers)) > self.max_headers_bytes:
            raise MessageBusCapacityError("message headers exceed configured bytes")
        if len(encoded) > self.max_draft_bytes:
            raise MessageBusCapacityError("message draft exceeds configured bytes")

    def _topic_keys(self, topic: str) -> dict[str, str]:
        digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:24]
        base = f"{self.namespace}:topic:{digest}"
        return {
            "sequence": f"{base}:sequence",
            "stream": f"{base}:stream",
            "index": f"{base}:index",
            "idempotency": f"{base}:idempotency",
            "unused": f"{base}:unused",
        }

    def _group_name(self, consumer_id: str) -> str:
        digest = hashlib.sha256(consumer_id.encode("utf-8")).hexdigest()[:20]
        return f"group-{digest}"

    def _cursor_field(self, consumer_id: str, topic: str) -> str:
        return hashlib.sha256(f"{consumer_id}\0{topic}".encode("utf-8")).hexdigest()

    def _acked_set_key(self, consumer_id: str, topic: str) -> str:
        return f"{self.namespace}:acked:{self._cursor_field(consumer_id, topic)}"

    @property
    def _cursor_hash_key(self) -> str:
        return f"{self.namespace}:cursors"

    @property
    def _event_sequence_key(self) -> str:
        return f"{self.namespace}:events:sequence"

    @property
    def _event_stream_key(self) -> str:
        return f"{self.namespace}:events:stream"


def _json_dump(value: object) -> str:
    return json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _validate_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value):
        raise ValueError(f"{name} must be a safe identifier")


__all__ = ["RedisStreamsMessageBusStore"]
