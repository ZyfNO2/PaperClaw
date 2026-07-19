# PaperClaw v0.31 — E2E Team Runtime, Aggregate Eval, and Message Bus Choreography

## Status

Implementation branch: `feat/v0.31-e2e-eval-messagebus`

This increment converts three existing foundations into one interview-grade backend story:

1. a real provider-capable end-to-end MultiAgent entrypoint;
2. aggregate latency/token/cost/failure evaluation over durable traces;
3. durable Message Bus consumption for Coordinator/Worker/Reviewer execution.

## Scope

### P0 — end-to-end team run

`paperclaw-team-run` accepts a bounded JSON team plan, reads the existing OpenAI-compatible provider configuration, submits the request to the durable Message Bus, runs the existing Coordinator, mirrors team events, records metrics, persists a terminal event, and acknowledges the request only after terminal persistence.

Deterministic unit acceptance uses Fake Models. A separate `real_llm` test is opt-in and requires provider credentials. Fake acceptance is never described as live-provider evidence.

### P1 — aggregate eval, cost, and observability

Add:

- exact-match operator-supplied model pricing;
- model-call latency/token/retry/cost instrumentation;
- per-run cost and quality reports from durable TraceEvent facts;
- aggregate success rate, tool failure rate, P50/P95/P99 latency, retries, tokens, estimated cost, unpriced call count, and failure taxonomy;
- `paperclaw-observe` CLI.

Pricing is policy, not historical fact. The repository does not embed mutable current provider prices. Missing prices are reported as unpriced instead of silently treated as zero-cost usage.

### P1 — Message Bus choreography

Add a consumer runtime with:

- direct team request messages;
- durable consumer cursor/ack;
- live Coordinator event mirroring;
- terminal result and metrics events;
- durable per-message attempt count;
- retry without ack on transient runtime failure;
- dead-letter after bounded attempts;
- idempotent request submission and event publication;
- restart behavior that acknowledges already-terminal requests without re-executing them.

The existing Coordinator remains the scheduling authority. This increment composes around it rather than duplicating DAG, budget, lease, cancellation, Worker, or Reviewer logic.

## Explicit non-goals

- no claim of exactly-once delivery;
- no Redis/Kafka/NATS adapter;
- no automatic classification of all provider errors as retryable/non-retryable;
- no hosted pricing lookup;
- no public multi-tenant queue;
- no merge to `main` in this development task.

## Acceptance

### Offline

- pricing and token-cost calculations;
- missing-price behavior;
- aggregate success/failure/latency percentiles;
- MeteredChatModel observations;
- exact request idempotency;
- durable request consumption;
- Coordinator event mirroring;
- metrics and terminal publication;
- ack only after terminal persistence;
- retry then DLQ at max attempts;
- Linux and Windows focused tests;
- full non-live regression and correctness Ruff.

### Live provider

Manual workflow only:

- real OpenAI-compatible provider;
- one bounded no-tool team task;
- terminal bus event;
- at least one metered model call;
- no claim of scientific quality.

## Interview claim boundary

Safe claim:

> PaperClaw can execute a bounded MultiAgent plan through a durable bus consumer, preserve idempotency and retry/DLQ state, mirror Coordinator/Worker/Reviewer events, and report latency, token usage, estimated cost, failure categories, and aggregate percentiles.

Unsafe claims:

- exactly-once processing;
- multi-host broker semantics;
- production pricing accuracy without an operator-supplied pricing file;
- live-provider acceptance when only Fake Model CI was run.
