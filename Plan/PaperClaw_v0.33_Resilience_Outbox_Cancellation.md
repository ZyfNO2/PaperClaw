# PaperClaw v0.33 — Resilience, Outbox, Cancellation and Idempotency

## Goal

Harden the v0.32 Team Run / Trace / Eval path against process-crash windows without
replacing the existing Coordinator or Message Bus contracts.

```text
request
  -> begin attempt
  -> Coordinator / Worker / Reviewer
  -> atomic SQLite transaction:
       terminal attempt state
       terminal snapshot
       pending Outbox rows
  -> exact-idempotent Bus publish
  -> mark Outbox delivered
  -> request Ack
```

## Scope

### Terminal Outbox

- terminal state and terminal publication intents commit in one SQLite transaction;
- metrics, terminal events, and DLQ messages are Outbox records;
- restart recovery flushes pending rows before request Ack;
- publish-before-delivered-mark replay uses the existing Message Bus idempotency key;
- terminal snapshots preserve request sequence, attempt, metrics and failure taxonomy.

### Failure injection and recovery

Deterministic checkpoints:

- `after_attempt_started`;
- `after_coordinator_completed`;
- `after_terminal_committed`;
- `after_outbox_published`;
- `before_request_ack`.

`InjectedCrash` is a test-only process-death surrogate. It is intentionally not
converted into a normal execution failure.

### Cancellation

```text
paperclaw-team-cancel
  -> multiagent.team.cancellations.v1
  -> request-specific cancellation consumer
  -> existing Coordinator.cancel(task_id, tasks)
  -> existing Worker cooperative cancel / process-tree termination
```

- cancellation requests are exact-idempotent by `cancellation_id`;
- empty task list means cancel every task in the request;
- accepted and rejected task ids are emitted as bounded events;
- cancellation messages are acknowledged only after the existing Coordinator
  cancellation entrypoint has been called.

### Retry taxonomy

- `retryable`: timeout, connection, interruption and OS transport failures;
- `permanent`: invalid input, type, permission and missing-file configuration failures;
- `unknown`: bounded retry until `max_attempts`.

Permanent failures enter DLQ immediately. Retryable and unknown failures remain
bounded by `max_attempts`.

## Acceptance

1. crash after terminal commit does not re-execute Coordinator;
2. crash after Bus publish but before delivered mark does not duplicate the event;
3. crash before request Ack only repairs Ack;
4. permanent failure enters DLQ on attempt one;
5. retryable timeout can succeed on the next attempt;
6. durable cancellation calls the existing Coordinator cancel path;
7. v0.32 Team Run / Trace / Eval tests remain green;
8. package `0.33.0` exposes `paperclaw-team-cancel`;
9. full non-live repository regression remains green.

## Explicit limits

- Outbox and attempt state are atomic with each other, not with an external broker;
- live Coordinator progress events remain direct best-effort publications;
- an external Tool side effect before terminal commit still needs Tool-level
  idempotency; v0.33 does not claim transactional files or shell commands;
- SQLite remains a same-filesystem reference backend;
- PostgreSQL + Redis Streams are v0.34 scope;
- cancellation delivery is polling-based and bounded by the configured poll interval.
