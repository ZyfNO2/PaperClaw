# PaperClaw v0.15 — Production Integration & Security

## 1. Objective

v0.15 closes the highest-priority interview and engineering gaps left after v0.12–v0.14:

1. connect the FastAPI/SSE application layer to the durable SQLite run state machine;
2. make event replay survive service restart;
3. define explicit disconnect, timeout and cancellation semantics;
4. place a non-model authorization boundary before every tool execution;
5. prove recovery behavior with deterministic integration and process-restart tests.

This version does **not** claim distributed exactly-once execution, arbitrary instruction-pointer recovery, or production multi-tenant isolation.

## 2. Architecture

```text
FastAPI / SSE
    ↓
DurableRunApplicationService
    ↓
SQLiteDurableRunStore + DurableEventStore
    ↓
Worker claim / lease / heartbeat
    ↓
QueryEngine
    ↓
ToolAuthorizationPolicy → Tool execution
```

SQLite remains the source of truth. In-memory conditions are only wake-up optimizations and must not be required for correctness.

## 3. MVP scope

### 3.1 Durable service integration

Implement a `DurableRunApplicationService` that owns:

- durable run creation and idempotency;
- worker claim and lease renewal;
- QueryEngine execution;
- durable state transitions;
- durable event append and monotonic sequence numbers;
- cooperative cancellation;
- terminal result persistence;
- startup recovery classification.

Required state flow:

```text
queued → running → cancelling → completed | failed | stopped | blocked
                   ↘ recovery_required
```

### 3.2 Durable SSE replay

`GET /v1/runs/{run_id}/events` must:

- accept `Last-Event-ID`;
- replay events with sequence greater than that ID from SQLite;
- continue polling/waiting for new events;
- emit heartbeats without advancing the cursor;
- terminate only after the run is terminal and no later event remains;
- reject invalid or negative cursors.

### 3.3 Disconnect policy

Support two explicit policies:

- `detach_on_disconnect` — default; the run continues;
- `cancel_on_disconnect` — request cancellation when the streaming client disconnects.

The selected policy must be persisted with the run request. A browser/network disconnect must never implicitly mean cancellation unless the policy explicitly says so.

### 3.4 Timeout policy

Create a typed `TimeoutPolicy` with distinct limits for:

- queue wait;
- provider/model call;
- tool call;
- whole run;
- graceful shutdown.

Errors must retain their layer-specific code. A provider timeout, tool timeout and run budget exhaustion must not collapse into one generic timeout.

### 3.5 Tool authorization policy

Every tool request must cross a deterministic, non-model authorization boundary.

Minimum risk levels:

- `read_only`;
- `workspace_write`;
- `external_write`;
- `destructive`.

Minimum checks:

- tool allowlist/capability exposure;
- workspace path containment;
- URL scheme and private-network/metadata endpoint blocking;
- argument validation;
- explicit approval requirement for external-write and destructive actions;
- redacted decision audit event.

The invariant is:

> Model-proposed action is a request; only the policy layer can authorize execution.

### 3.6 Recovery behavior

On startup, expired or abandoned active runs must be classified:

- safe retry → return to `queued`;
- known terminal receipt → finalize from durable evidence;
- uncertain side effect → `recovery_required`.

No automatic retry is allowed when an external side effect may have happened but no durable receipt proves its outcome.

### 3.7 MVP tests

Required automated coverage:

1. API create → durable row → worker claim → terminal result;
2. idempotency survives service recreation;
3. SSE replays persisted events after service recreation;
4. only one worker wins a claim;
5. cancellation before and after runtime `run_id` assignment;
6. expired lease safe-retry classification;
7. uncertain action enters `recovery_required`;
8. path traversal denied;
9. private-network/metadata URL denied;
10. high-risk tool denied without approval;
11. plugin failure cannot grant permission;
12. timeout codes remain layer-specific.

A subprocess restart smoke test should create a durable run/event fixture in one process and verify recovery/replay in a second process. It must not claim recovery of an arbitrary live Provider TCP connection.

## 4. Plugin boundaries after MVP

Plugins are static, explicitly registered and fail closed when they affect authorization or recovery.

### 4.1 Queue plugin

`QueueBackendPlugin`

Future adapters:

- `RedisStreamsQueuePlugin`;
- PostgreSQL SKIP LOCKED worker queue;
- cloud queue adapter.

Contract includes enqueue, claim, ack, retry/backoff and dead-letter behavior. The queue is not the source of truth for final run state.

### 4.2 Authorization plugins

- `ToolRiskClassifierPlugin`;
- `ToolApprovalPlugin`;
- `TenantAuthorizationPlugin`;
- `NetworkEgressPolicyPlugin`.

A plugin exception must produce denial, never implicit approval.

### 4.3 Resilience plugins

- `ProviderCircuitBreakerPlugin`;
- `ProviderFallbackPlugin`;
- `RateLimitPlugin`;
- `BudgetPolicyPlugin`.

Retry classification must distinguish authentication, 429, 5xx, network, context-overflow and invalid-response errors.

### 4.4 Telemetry plugins

- `OpenTelemetryExporterPlugin`;
- `PrometheusMetricsPlugin`;
- `JsonLogExporterPlugin`.

Exporters receive already-redacted events and must not receive raw credentials.

### 4.5 Durable storage plugins

- PostgreSQL durable store;
- external blob/checkpoint store;
- durable event notification backend.

SQLite remains the reference MVP implementation.

## 5. Non-goals

- Kafka or Kubernetes;
- distributed exactly-once claims;
- automatic replay of arbitrary destructive tools;
- autonomous approval by another LLM;
- full OAuth/RBAC product implementation;
- recovery of an in-flight HTTP response stream;
- replacing v0.14 evaluation adapters.

## 6. Definition of done

v0.15 MVP is complete only when:

- the public API uses the durable service path by default;
- run state, idempotency and event replay survive service restart;
- cancellation and disconnect policies are explicit and tested;
- tool authorization executes before tool invocation and fails closed;
- deterministic restart/recovery tests pass;
- full non-live CI and desktop packaging remain green;
- known limitations and exact-head evidence are written to `artifacts/v0_15/`;
- the pull request remains Draft until real Provider and manual process-kill acceptance are recorded.
