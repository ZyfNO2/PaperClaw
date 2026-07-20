# PaperClaw v0.34 — PostgreSQL + Redis Streams Multiprocess Runtime

## Goal

Move the v0.33 durable choreography from same-filesystem reference storage to
real shared services without changing the stable runtime contracts.

```text
Redis Streams MessageBusStore
  -> Consumer Group / Pending Entries / XAUTOCLAIM
  -> ResilientBusDrivenTeamRuntime in multiple processes
  -> PostgreSQL attempt, terminal snapshot and ordered Outbox
  -> exact-idempotent Redis terminal publication
  -> contiguous logical Ack cursor
```

## Redis Streams Message Bus

- one Redis Stream per logical Topic;
- Lua-atomic sequence allocation, capacity check, stream append, idempotency binding
  and audit-event append;
- exact idempotency scope remains `(topic, sender_id, idempotency_key)`;
- one Consumer Group per logical `consumer_id`;
- unique process consumer names;
- `XAUTOCLAIM` recovery for abandoned Pending Entries;
- direct-recipient filtering inside each logical consumer group;
- out-of-order physical `XACK` with a separate contiguous logical cursor;
- stable MessageBusStore API used by the existing Runtime and cancellation CLI.

## PostgreSQL Choreography Store

- attempt state and failure disposition;
- terminal snapshot;
- ordered terminal Outbox in the same PostgreSQL transaction;
- `ordinal` is the publication order and hash IDs remain identity only;
- `FOR UPDATE SKIP LOCKED` Outbox claim for multiple publisher processes;
- stale claim takeover;
- JSONB payload and header storage;
- schema name is explicit and validated.

## CLI

`paperclaw-team-run` supports:

```text
--bus-backend sqlite|redis
--redis-url
--redis-namespace
--state-backend sqlite|postgres
--postgres-dsn
--postgres-schema
```

`paperclaw-team-cancel` supports the same SQLite/Redis bus selection.

Environment alternatives:

```text
PAPERCLAW_REDIS_URL
PAPERCLAW_POSTGRES_DSN
```

## Acceptance

Real GitHub Actions services:

- Redis 7;
- PostgreSQL 16.

Tests verify:

1. Redis exact idempotency and conflict detection;
2. different senders may reuse the same idempotency key;
3. out-of-order worker Ack advances only a contiguous logical cursor;
4. abandoned Pending Entries are claimed by another process;
5. PostgreSQL terminal state and ordered Outbox commit atomically;
6. concurrent Outbox claim uses `SKIP LOCKED` without duplicate claims;
7. two spawned Python worker processes share one Consumer Group;
8. each Team Request reaches one acknowledged terminal result without duplicates;
9. v0.33 resilience and v0.32 observability compatibility remain green;
10. wheel `0.34.0` installs with the `distributed` extra.

## Explicit limits

- Redis Cluster cross-slot Lua deployment is not claimed; a single Redis service or
  compatible colocated-key deployment is the acceptance target;
- PostgreSQL and Redis do not form one distributed transaction;
- terminal Outbox replay provides at-least-once publication with exact idempotency;
- Trace projection remains the existing local SQLite reference store in this version;
- external Tool side effects still require Tool-level idempotency;
- TLS, credential rotation, backups and hosted operations are deployment concerns;
- no Kafka, NATS or RabbitMQ adapter is claimed.
