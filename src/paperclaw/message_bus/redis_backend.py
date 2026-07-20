"""Contract-correct public Redis Streams backend.

The low-level stream implementation is reused for pull, Ack, pending claim and
audit behavior. Publish is overridden so exact idempotency preserves the stable
SQLite contract: ``(topic, sender_id, idempotency_key)``.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .contracts import (
    MessageBusCapacityError,
    MessageBusConflictError,
    MessageDraft,
    PublishResult,
    canonical_draft_bytes,
)
from .redis_streams import (
    RedisStreamsMessageBusStore as _BaseRedisStreamsMessageBusStore,
    _json_dump,
    _text,
)

_PUBLISH_V2 = r"""
local existing = redis.call('HGET', KEYS[4], ARGV[1])
if existing then
  local decoded = cjson.decode(existing)
  if decoded['digest'] ~= ARGV[2] then return {'CONFLICT'} end
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
    'sequence', '', 'message_id', '', 'consumer_id', '',
    'metadata_json', ARGV[13], 'created_at', ARGV[9])
  return {'CAPACITY'}
end
local sequence = redis.call('INCR', KEYS[1])
local stream_id = redis.call('XADD', KEYS[2], '*',
  'sequence', tostring(sequence),
  'sender_id', ARGV[4],
  'recipient_id', ARGV[5],
  'idempotency_key', ARGV[8],
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


class RedisStreamsMessageBusStore(_BaseRedisStreamsMessageBusStore):
    """Stable public Redis Streams MessageBusStore implementation."""

    def __init__(self, redis_url: str, **kwargs: Any) -> None:
        kwargs.setdefault("claim_idle_ms", 30_000)
        super().__init__(redis_url, **kwargs)
        self._publish_script = self._redis.register_script(_PUBLISH_V2)

    def publish(self, draft: MessageDraft) -> PublishResult:
        encoded = canonical_draft_bytes(draft)
        self._validate_sizes(draft, encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        topic_keys = self._topic_keys(draft.topic)
        metadata = {
            "sender_id": draft.sender_id,
            "recipient_id": draft.recipient_id,
        }
        idempotency_field = f"{draft.sender_id}\x1f{draft.idempotency_key}"
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
                idempotency_field,
                digest,
                draft.topic,
                draft.sender_id,
                draft.recipient_id or "",
                _json_dump(draft.payload),
                _json_dump(draft.headers),
                draft.idempotency_key,
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


__all__ = ["RedisStreamsMessageBusStore"]
