# PaperClaw v0.25 Distributed Store / Queue Foundation

> Status: implementation in progress  
> Stack base: `feat/v0.24-remote-worker-gateway @ 8e872f4303718d0d287316162a2c3c568b13d6cc`  
> Branch: `feat/v0.25-distributed-store-queue`

## 1. Goal

Externalize the durable-task ownership contract from the single concrete SQLite class and add a real fencing generation so stale workers cannot mutate a task after lease expiry/reclaim.

v0.25 is the ownership/queue foundation required before PaperClaw may safely claim parallel remote writers.

```text
BackgroundTaskSupervisor
        -> DurableTaskStore protocol
        -> atomic claim
        -> lease owner + lease_generation fencing token
        -> heartbeat / start / side-effect / complete / requeue all fenced
```

## 2. Scope

### Included

- `DurableTaskStore` Protocol consumed by runtime composition;
- explicit `lease_generation` on `TaskRecord`;
- SQLite schema migration v1 -> v2;
- monotonically increasing generation on every successful claim;
- owner mutations require both optimistic task version and lease generation;
- stale generation rejection after expiry/recovery/reclaim, even when worker ID is reused;
- claim events include generation;
- recovery leaves old generations permanently stale;
- multi-process SQLite contention acceptance over one shared DB file;
- exact-once-per-generation claim evidence;
- full repository regression.

### Explicitly excluded

- claiming SQLite is a multi-host distributed database;
- Redis/PostgreSQL production adapter unless actually validated against a real shared service;
- remote worker discovery/load balancing;
- Agent Message Bus;
- distributed file locking;
- exactly-once side effects.

## 3. Why version is not a fencing token

The existing store uses `TaskRecord.version` for optimistic state transitions. That value changes for general task mutations and is not a dedicated ownership epoch. A distributed worker needs a monotonic token tied specifically to lease acquisition.

v0.25 separates:

```text
version          -> optimistic record mutation/version check
lease_generation -> ownership fencing epoch, incremented only on claim
```

A worker must present the generation issued by its claim for every owner-only mutation.

## 4. Fencing invariants

1. Initial generation = 0.
2. Successful claim: `lease_generation = lease_generation + 1` atomically with queued -> claimed.
3. The claimed `TaskRecord` carries the new generation.
4. `start_task`, `heartbeat`, `mark_side_effect_state`, `complete_task`, and `requeue_task` require exact generation match.
5. Expiry/recovery does not reset generation.
6. Any later reclaim has a strictly larger generation.
7. A stale owner with the same `worker_id` but an older generation is rejected.
8. A stale owner can never heartbeat a new lease, mark side effects, complete, or requeue the reclaimed task.

## 5. Store protocol

The runtime must depend on a structural `DurableTaskStore` protocol rather than `SQLiteDurableTaskStore`.

Required operations cover:

- create/get/list;
- dependency refresh;
- claim/start/heartbeat;
- side-effect state;
- cancel;
- complete/requeue;
- expired lease recovery;
- event listing.

This freezes the adapter seam for a later PostgreSQL/shared-store implementation.

## 6. SQLite reference semantics

SQLite remains a reference/local shared-file implementation.

- `BEGIN IMMEDIATE` serializes writers;
- WAL remains enabled;
- `busy_timeout` bounds lock contention;
- multi-process tests use independent Python processes and independent store connections against one DB file;
- this proves same-filesystem multi-process contention/fencing, **not** multi-host distribution.

## 7. Migration

Schema v1 databases are migrated in-place to v2:

```text
ALTER TABLE background_tasks
ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0
```

Then schema metadata becomes version 2.

Migration must be idempotent and preserve existing task/event/idempotency records.

## 8. Acceptance matrix

- fresh DB generation starts at 0;
- first claim returns generation 1;
- requeue/reclaim returns generation 2;
- stale generation cannot start;
- stale generation cannot heartbeat;
- stale generation cannot mark side effect;
- stale generation cannot complete;
- stale generation cannot requeue;
- same worker ID reused with old generation is still rejected;
- expired lease recovery + reclaim strictly increments generation;
- v1 DB migrates to v2 without losing records;
- multiple processes racing `claim_next` never claim the same task in the same generation;
- all queued tasks are claimed at most once per generation under contention;
- runtime Supervisor passes generation on all owner mutations;
- full Windows non-live regression and Ruff pass.

## 9. GO / NO-GO

### GO

- ownership fencing is explicit and monotonic;
- runtime no longer types itself to concrete SQLite store;
- stale owners are rejected after reclaim;
- multi-process contention evidence passes;
- no multi-host claim is made without a validated external shared-store adapter.

### NO-GO

- worker ID alone authorizes mutation;
- task version is still treated as the only lease fence;
- lease recovery can reset/reuse generation;
- stale worker can complete a reclaimed task;
- SQLite shared-file evidence is described as multi-host distributed safety.

## 10. Follow-on

A later shared-store adapter may implement this frozen protocol using PostgreSQL/another external transactional store and must prove the same fencing matrix against the real service.

After ownership semantics are stable:

```text
v0.26 Agent Message Bus
  -> durable typed envelopes
  -> topic/recipient routing
  -> sequence ordering + idempotent publish
  -> consumer cursor/ack
  -> backpressure + audit evidence
```
