# PaperClaw v0.25 Distributed Store / Queue Foundation — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

- Repository: `ZyfNO2/PaperClaw`
- Stack base: `feat/v0.24-remote-worker-gateway @ 8e872f4303718d0d287316162a2c3c568b13d6cc`
- Branch: `feat/v0.25-distributed-store-queue`
- Draft PR: `#54`
- Exact validated implementation SHA: `a4d5bb6fcc7c99f10e55f9879693791c266c9b2c`
- Plan: `Plan/PaperClaw_v0.25_Distributed_Store_Queue_Foundation.md`

## Delivered

v0.25 externalizes the durable ownership seam and introduces a dedicated fencing generation before any parallel remote-writer claim is made.

### Public store contracts

- `DurableTaskStore`
- `FencedDurableTaskStore`
- `TaskLease`
- `FencedSQLiteDurableTaskStore`
- `StrictFencedSQLiteDurableTaskStore`

These are exported from `paperclaw.tasks` so a future external shared-store adapter does not depend on internal module paths.

### Dedicated ownership epoch

A claim now returns:

```text
TaskLease(
  task=TaskRecord(...),
  worker_id=...,
  generation=N,
)
```

`TaskRecord.version` remains the optimistic record version. `TaskLease.generation` is the ownership fencing epoch.

Generation allocation is atomic with `queued -> claimed` inside one SQLite `BEGIN IMMEDIATE` transaction.

### Sidecar fencing persistence

The implementation intentionally does **not** modify the historical `background_tasks` schema.

It adds:

```sql
background_task_fencing(
  task_id PRIMARY KEY,
  generation,
  updated_at
)
```

Benefits:

- old task rows stay compatible;
- fencing lifecycle is independent from ordinary record versioning;
- old databases gain fencing idempotently;
- existing tasks/events/idempotency rows are preserved.

### Fenced owner-only mutation

The following require exact current generation in addition to worker/version checks:

- `start_task_fenced`
- `heartbeat_fenced`
- `mark_side_effect_state_fenced`
- `complete_task_fenced`
- `requeue_task_fenced`

A stale owner cannot mutate a reclaimed task even when:

- the same `worker_id` is reused;
- the caller presents the current task record version;
- the old lease object still exists in another process.

### Strict production store

Production runtime composition now constructs:

```text
StrictFencedSQLiteDurableTaskStore
```

It rejects historical unfenced ownership operations:

- `claim_next`
- `start_task`
- `heartbeat`
- `mark_side_effect_state`
- `complete_task`
- `requeue_task`

This closes the accidental bypass path where a caller could otherwise use the inherited legacy methods and omit the generation.

### Runtime propagation

`BackgroundTaskSupervisor` now consumes the backend-neutral durable store seam and carries the claim generation through:

- start;
- heartbeat;
- completion;
- retry/requeue.

Legacy direct-store tests retain an explicit compatibility fallback; production composition uses the strict fenced path.

## Multi-process contention evidence

The focused acceptance starts four independent Python processes using multiprocessing `spawn`.

Each process:

- opens its own store/SQLite connection;
- races `claim_next_lease()` against the same DB file;
- claims from 24 queued tasks.

Assertions:

- exactly 24 claims total;
- every task ID is unique;
- every `(task_id, generation)` pair is unique;
- every initial claim generation is 1.

The same test passes on Linux and Windows.

This is evidence for **same-filesystem multi-process contention/fencing** only. It is not a multi-host database claim.

## Lease recovery evidence

Validated sequence:

```text
claim generation 1
  -> lease expires
  -> recover_expired_leases()
  -> task queued again
  -> reclaim generation 2
  -> any generation-1 owner mutation rejected
```

Generation is never reset by recovery.

## Validation

Exact implementation SHA:

```text
a4d5bb6fcc7c99f10e55f9879693791c266c9b2c
```

GitHub Actions run:

```text
29656257992
```

Results:

- Ubuntu fenced-store focused acceptance — SUCCESS
- Windows fenced-store focused acceptance — SUCCESS
- Linux/Windows spawned multi-process contention — SUCCESS
- all durable task compatibility tests — SUCCESS
- scoped Ruff — SUCCESS
- full Windows `-m "not real_llm"` repository regression — SUCCESS
- repository correctness Ruff — SUCCESS

Machine-readable regression evidence:

```text
876 passed / 0 failed
artifact: v025-full-regression-29656257992
digest: sha256:56c4f0ba3c229f1f78bff4aec2894a308c1b53c1412552864dcf717de895e38f
```

## Preserved negative evidence / corrections

1. The first v0.25 workflow referenced a nonexistent `tests/unit/tasks/test_task_runtime.py`; focused CI failed before product tests. The workflow path was corrected. Product behavior was not weakened.
2. The initial Plan proposed a `background_tasks` schema v1 -> v2 migration with `lease_generation` on `TaskRecord`. Implementation review showed a cleaner compatibility boundary: `TaskLease.generation` plus an additive sidecar fencing table. The final Plan/Handoff now match the actual code.
3. Inheritance initially left legacy unfenced owner methods callable on the fenced SQLite subclass. A strict production subclass was added so production composition cannot bypass the generation contract.

## Important limits

v0.25 does **not** claim:

- PostgreSQL/Redis production support;
- multi-host ownership safety;
- distributed consensus;
- distributed file locks;
- exactly-once side effects;
- safe parallel remote writers across machines.

SQLite validation uses independent processes against one shared DB file. A real multi-host claim requires an external transactional store adapter validated against an actual shared service with the same fencing matrix.

## Main files

- `src/paperclaw/tasks/distributed_store.py`
- `src/paperclaw/tasks/strict_store.py`
- `src/paperclaw/tasks/runtime.py`
- `src/paperclaw/tasks/bootstrap.py`
- `src/paperclaw/tasks/__init__.py`
- `tests/unit/tasks/test_fenced_store.py`
- `tests/unit/tasks/test_strict_fenced_store.py`
- `.github/workflows/v025-distributed-store-queue.yml`

## Next line

### v0.26 Agent Message Bus

Build a durable pull/cursor bus foundation on explicit contracts:

- immutable typed message envelope;
- per-topic monotonically increasing sequence;
- idempotent publish with conflict detection;
- broadcast/direct recipient routing;
- independent consumer cursors;
- monotonic/idempotent ack;
- explicit capacity/backpressure rejection;
- durable audit events;
- multi-process publisher contention tests.

Do not claim Kafka/NATS/Redis semantics unless a real external broker adapter is implemented and validated.

## Final classification

**COMPLETE**

PR remains Draft and unmerged.
