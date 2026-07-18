# PaperClaw v0.25 Distributed Store / Queue Foundation

> Status: implementation complete / acceptance complete  
> Stack base: `feat/v0.24-remote-worker-gateway @ 8e872f4303718d0d287316162a2c3c568b13d6cc`  
> Branch: `feat/v0.25-distributed-store-queue`  
> Draft PR: `#54`  
> Validated implementation SHA: `a4d5bb6fcc7c99f10e55f9879693791c266c9b2c`

## 1. Goal

Externalize the durable-task ownership contract from one concrete SQLite class and add a dedicated monotonic fencing generation so stale workers cannot mutate a task after lease expiry/reclaim.

v0.25 is the ownership/queue foundation required before PaperClaw may safely consider parallel remote writers.

```text
BackgroundTaskSupervisor
        -> DurableTaskStore protocol
        -> atomic fenced claim
        -> TaskLease(worker_id, generation, task)
        -> start / heartbeat / side-effect / complete / requeue all generation-fenced
```

## 2. Implemented scope

- public `DurableTaskStore` protocol consumed by runtime composition;
- public `FencedDurableTaskStore` protocol for owner-only operations;
- explicit immutable `TaskLease` carrying the fencing generation;
- independent sidecar fencing table, leaving the historical `TaskRecord` schema compatible;
- monotonically increasing generation on every successful claim;
- owner mutations require worker ID + optimistic task version + lease generation;
- stale generation rejection after expiry/recovery/reclaim, even when worker ID is reused;
- claim/terminal/requeue events record the generation;
- recovery leaves old generations permanently stale;
- production `StrictFencedSQLiteDurableTaskStore` disables historical unfenced owner mutation APIs;
- multi-process SQLite contention acceptance over one shared DB file using independent spawned Python processes;
- full repository regression.

## 3. Explicit exclusions

- claiming SQLite is a multi-host distributed database;
- PostgreSQL/Redis production adapter without real service validation;
- remote worker discovery/load balancing;
- distributed file locking;
- exactly-once side effects;
- Agent Message Bus implementation in this release.

## 4. Why `version` is not the fencing token

The historical store uses `TaskRecord.version` for optimistic record state transitions. It changes for general task mutations and is not a dedicated ownership epoch.

v0.25 separates:

```text
TaskRecord.version  -> optimistic record mutation/version check
TaskLease.generation -> ownership fencing epoch, incremented only on successful claim
```

The generation is intentionally **not** added to the historical `TaskRecord` schema. A claim returns a separate `TaskLease`, and owner-only mutations must present its generation explicitly.

## 5. Fencing persistence

The SQLite reference implementation adds an additive sidecar table:

```sql
CREATE TABLE IF NOT EXISTS background_task_fencing (
    task_id TEXT PRIMARY KEY REFERENCES background_tasks(task_id),
    generation INTEGER NOT NULL CHECK(generation >= 1),
    updated_at REAL NOT NULL
);
```

There is no `background_tasks` v1 -> v2 column migration in this implementation.

Benefits:

- existing task rows/schema stay compatible;
- generation lifecycle is independent from normal task record versions;
- old databases gain fencing idempotently via `CREATE TABLE IF NOT EXISTS`;
- existing task/event/idempotency records are preserved.

## 6. Atomic claim contract

`claim_next_lease()` executes generation allocation and queue ownership transition in the same inherited SQLite transaction (`BEGIN IMMEDIATE`):

1. select one queued task;
2. read current sidecar generation;
3. compute `generation + 1` (or `1` on first claim);
4. upsert sidecar generation;
5. atomically transition `queued -> claimed`, increment attempt/version, and write lease owner/expiry;
6. append `task.claimed` event with `lease_generation`;
7. return `TaskLease`.

A transaction rollback rolls back both generation advancement and ownership acquisition.

## 7. Fencing invariants

1. No sidecar row means current generation 0.
2. First successful claim returns generation 1.
3. Every later successful reclaim returns a strictly larger generation.
4. Recovery/expiry never resets generation.
5. `start_task_fenced`, `heartbeat_fenced`, `mark_side_effect_state_fenced`, `complete_task_fenced`, and `requeue_task_fenced` require exact current generation.
6. Worker ID equality is insufficient authorization.
7. A stale owner remains stale even when the same `worker_id` is reused and the caller somehow has the current task record version.
8. A stale owner cannot heartbeat, mark side effects, complete, or requeue a reclaimed task.

## 8. Strict production boundary

`FencedSQLiteDurableTaskStore` preserves historical APIs for compatibility/reference tests.

Production composition uses:

```text
StrictFencedSQLiteDurableTaskStore
```

It rejects legacy unfenced owner operations:

- `claim_next`
- `start_task`
- `heartbeat`
- `mark_side_effect_state`
- `complete_task`
- `requeue_task`

and requires their generation-fenced equivalents.

This prevents accidental bypass of the ownership epoch in production composition.

## 9. Runtime/store seam

`BackgroundTaskSupervisor` is typed against the public `DurableTaskStore` protocol.

For a fenced store it propagates one claim context:

```text
TaskRecord + lease_generation
```

through:

- start;
- heartbeat;
- completion;
- retry/requeue.

Legacy direct-store tests remain compatible through an explicit fallback path, while production runtime constructs the strict fenced store.

## 10. SQLite reference semantics

SQLite remains a local/shared-filesystem reference implementation.

- `BEGIN IMMEDIATE` serializes writers;
- WAL remains enabled by the historical store;
- `busy_timeout` bounds lock contention;
- contention tests use independent `spawn` processes and independent connections against one DB file;
- Linux and Windows both pass the same multi-process claim matrix.

This proves **same-file multi-process** ownership/fencing, not multi-host distributed database safety.

## 11. Acceptance matrix

Validated:

- first claim generation 1;
- requeue/reclaim generation 2;
- stale generation cannot start;
- stale generation cannot heartbeat;
- stale generation cannot mark side effects;
- stale generation cannot complete;
- stale generation cannot requeue;
- same worker ID reused with old generation is still rejected;
- expired lease recovery + reclaim strictly increments generation;
- claim event records generation;
- strict production store rejects all unfenced owner APIs;
- four independent spawned processes racing 24 tasks claim each task exactly once in generation 1;
- Linux focused matrix passes;
- Windows `spawn` focused matrix passes;
- all task compatibility tests pass;
- full Windows non-live repository regression passes;
- high-signal Ruff passes.

## 12. Validation

Exact implementation SHA:

```text
a4d5bb6fcc7c99f10e55f9879693791c266c9b2c
```

GitHub Actions run:

```text
29656257992
```

Machine-readable regression:

```text
876 passed / 0 failed
artifact: v025-full-regression-29656257992
digest: sha256:56c4f0ba3c229f1f78bff4aec2894a308c1b53c1412552864dcf717de895e38f
```

## 13. GO / NO-GO

### GO

- ownership fencing is explicit and monotonic;
- production owner operations cannot bypass generation checks;
- runtime depends on a public backend-neutral store protocol;
- stale owners are rejected after reclaim;
- multi-process contention evidence passes on Linux and Windows;
- full repository regression is green;
- no multi-host claim is made without a validated external shared-store adapter.

### NO-GO

- worker ID alone authorizes owner mutation;
- task record version is treated as the only lease fence;
- lease recovery resets/reuses generation;
- stale worker can complete a reclaimed task;
- SQLite shared-file evidence is described as multi-host distributed safety;
- exactly-once side effects are claimed.

## 14. Follow-on

A later external transactional store may implement the public protocols and must prove the same fencing matrix against the real shared service before any multi-host claim.

Next release line:

```text
v0.26 Agent Message Bus
  -> durable typed envelopes
  -> topic/recipient routing
  -> per-topic sequence ordering + idempotent publish
  -> consumer cursor/ack
  -> explicit capacity/backpressure
  -> audit evidence
```
