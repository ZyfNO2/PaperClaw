# PaperClaw v0.26 Agent Message Bus Foundation

> Status: implementation in progress  
> Stack base: `feat/v0.25-distributed-store-queue @ 52d313ee6cb4421b7f8e1a5d73cda62b2cecbf8b`  
> Branch: `feat/v0.26-agent-message-bus`

## 1. Goal

Add a durable typed pull/cursor message bus foundation for Agent-to-Agent communication without claiming Kafka/NATS/Redis semantics.

```text
publisher
  -> MessageBusStore.publish()
  -> durable topic sequence
  -> routing filter
  -> consumer pull after cursor
  -> explicit ack
```

## 2. Included

- immutable `MessageEnvelope` contract;
- JSON-safe bounded payload/headers;
- credential-shaped field rejection;
- per-topic monotonically increasing sequence;
- idempotent publish by `(topic, sender_id, idempotency_key)`;
- same key + different digest conflict rejection;
- broadcast messages (`recipient_id = null`);
- direct messages (`recipient_id = consumer_id`);
- independent per-consumer topic cursors;
- monotonic/idempotent ack;
- explicit topic capacity/backpressure rejection;
- durable audit events;
- SQLite shared-file reference implementation;
- Linux/Windows spawned multi-process publisher contention;
- full repository regression.

## 3. Explicit exclusions

- Kafka/NATS/Redis production adapter;
- multi-host broker claim;
- exactly-once delivery;
- push/websocket delivery;
- automatic retry/dead-letter policy;
- distributed consensus;
- automatic replacement of the durable task queue.

## 4. Envelope contract

`MessageEnvelope`:

```text
message_id
topic
sequence
sender_id
recipient_id?       # null = broadcast
idempotency_key
payload              # JSON object
headers              # JSON object
created_at
```

Rules:

- immutable/frozen;
- bounded IDs/topic;
- sequence positive;
- JSON objects only, no NaN;
- payload/headers reject credential-shaped keys;
- no hidden reasoning/secret transport.

## 5. Publish idempotency

Idempotency key scope:

```text
(topic, sender_id, idempotency_key)
```

- first publish -> allocates next topic sequence;
- exact semantic retry -> returns existing envelope;
- same key + different canonical digest -> conflict;
- sequence allocation and insert occur in one transaction;
- publish never silently overwrites.

## 6. Ordering

Each topic has one monotonically increasing sequence.

Consumers observe messages in ascending topic sequence after their current cursor.

Multi-process publishers must never create duplicate topic sequences.

## 7. Routing

A consumer can receive:

- broadcast: `recipient_id IS NULL`;
- direct: `recipient_id == consumer_id`.

Direct messages for another consumer are not delivered.

## 8. Cursor / ack

Cursor key:

```text
(consumer_id, topic)
```

Ack rules:

- cursor only moves forward;
- repeated ack of same/lower sequence is idempotent;
- ack cannot move beyond the latest message eligible for that consumer;
- pull itself does not advance cursor;
- no implicit deletion on ack.

## 9. Backpressure

A configurable per-topic hard retained-message limit is enforced before insert.

When full:

```text
publish -> MessageBusCapacityError
```

Messages are not silently dropped and old messages are not automatically evicted in v0.26.

Retention/compaction policy is a later concern.

## 10. Audit

Durable events record bounded metadata for:

- message published;
- publish deduplicated;
- cursor acknowledged;
- capacity rejection where practical.

Payload bodies are not duplicated into audit event metadata.

## 11. Acceptance matrix

- first publish sequence 1;
- subsequent publish increments sequence;
- idempotent retry returns same message;
- conflicting idempotency key rejected;
- broadcast visible to multiple consumers;
- direct message visible only to recipient;
- independent consumer cursors;
- ack monotonic/idempotent;
- ack beyond eligible sequence rejected;
- hard topic capacity rejects without deleting old messages;
- nested credential-shaped payload/header fields rejected;
- four spawned processes publish concurrently to one SQLite file with unique contiguous sequences;
- Linux + Windows focused tests;
- full Windows non-live regression;
- Ruff.

## 12. Claim boundary

SQLite is a same-filesystem durable reference implementation only.

Passing multi-process tests does not make it a multi-host message broker.

A real Kafka/NATS/Redis/PostgreSQL-backed bus must independently validate these contracts before any external broker claim.

## 13. GO / NO-GO

### GO

- durable typed envelopes and ordering are deterministic;
- publish idempotency is conflict-safe;
- routing/cursors are consumer-isolated;
- backpressure fails closed;
- multi-process sequence allocation is contention-safe on Linux/Windows;
- full repository regression green.

### NO-GO

- silent message drop/overwrite;
- ack moves cursor backwards or past eligible messages;
- idempotency conflict silently reuses old payload;
- secrets allowed in envelope payload/headers;
- SQLite evidence described as a multi-host broker.
