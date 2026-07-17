# PaperClaw v0.12 Service API — MVP + Plugin Plan

> Status: READY FOR IMPLEMENTATION  
> Target branch: feature branch created from the documentation-updated `main`  
> Baseline: PaperClaw v0.11 Runtime / QueryEngine / Trace / Desktop  
> Goal: expose the existing synchronous Agent Runtime through a narrow, testable asynchronous HTTP service without rewriting the Runtime.

## 1. Why this stage exists

PaperClaw already has a stable synchronous `QueryEngine`, cooperative cancellation, ordered lifecycle events, Trace, SQLite persistence, TUI, and Desktop clients. The missing backend-facing capability is a service boundary that can:

- accept tasks over HTTP;
- execute the synchronous Runtime outside the ASGI event loop;
- stream ordered Agent events;
- expose cancellation and current state;
- reject duplicate submissions;
- enforce bounded concurrency and backpressure;
- remain optional so the core installation does not require a web framework.

This stage is an adapter and application-service layer, not a Runtime rewrite.

## 2. Architecture boundary

```text
HTTP / SSE
    |
FastAPI adapter
    |
RunApplicationService
    |
QueryEngineFactory -> QueryEngine -> AgentRuntimeExecutor
```

Rules:

1. FastAPI routes do not execute tools or construct prompts.
2. `RunApplicationService` owns service-level lifecycle, idempotency, worker threads, subscribers, and public projections.
3. `QueryEngine` remains the authoritative per-run execution façade.
4. Provider secrets never enter public events, response bodies, logs, idempotency records, or plugin payloads.
5. Existing CLI, TUI, Desktop, Trace, MCP, and Retrieval paths remain compatible.

## 3. MVP scope

### 3.1 Optional dependency and entrypoint

Add an optional dependency group:

```toml
service = [
  "fastapi>=0.115,<1",
  "uvicorn>=0.34,<1",
]
```

Add an explicit entrypoint:

```text
paperclaw-api
```

The base package must remain importable without FastAPI or Uvicorn installed.

### 3.2 Public API

Minimum routes:

```text
POST /v1/runs
GET  /v1/runs/{run_id}
GET  /v1/runs/{run_id}/events
POST /v1/runs/{run_id}/cancel
GET  /health
```

`POST /v1/runs` accepts:

- task text;
- workspace;
- bounded `RunLimits`;
- optional conversation ID;
- optional idempotency key.

The route returns `202 Accepted` with a service-generated public run ID.

### 3.3 Async boundary

- ASGI handlers remain non-blocking.
- Synchronous `QueryEngine.submit()` runs in a bounded worker pool.
- Each service run has one execution future and one authoritative terminal result.
- Request timeout is distinct from Agent execution limits.
- Disconnecting an HTTP client does not silently cancel an Agent run.
- Cancellation is explicit through the cancel endpoint.

### 3.4 SSE event contract

Events must include:

- service run ID;
- Runtime run ID when available;
- monotonically increasing service sequence;
- event type;
- sanitized payload;
- terminal marker;
- timestamp.

Requirements:

- support `Last-Event-ID`;
- replay bounded retained events;
- emit heartbeat comments;
- stop after the terminal event;
- never block Runtime callbacks indefinitely;
- cap per-subscriber queue length;
- disconnect slow consumers with a typed reason instead of exhausting memory.

### 3.5 Idempotency and concurrency

MVP rules:

- identical `Idempotency-Key` values return the original service run;
- an idempotency key cannot be reused with a different normalized request digest;
- configurable global active-run limit;
- configurable per-client active-run limit when a client identifier is supplied;
- rejected requests return typed HTTP errors;
- no distributed idempotency claim in the MVP.

### 3.6 Public error model

Use bounded errors such as:

- `invalid_request`;
- `run_not_found`;
- `idempotency_conflict`;
- `concurrency_limit_reached`;
- `run_not_cancellable`;
- `service_shutting_down`;
- `runtime_failed`.

Raw tracebacks, Provider bodies, API keys, and arbitrary tool output must not cross the HTTP boundary.

## 4. MVP deliverables

Suggested modules:

```text
src/paperclaw/service/
  __init__.py
  contracts.py
  application.py
  event_buffer.py
  fastapi_app.py
  runtime_factory.py
  entrypoint.py
```

Tests:

```text
tests/unit/service/
tests/integration/service/
```

Artifacts:

```text
artifacts/v0_12/implementation_summary.md
artifacts/v0_12/test_report.md
artifacts/v0_12/known_limitations.md
docs/handoff/PaperClaw_v0.12_Service_API_HANDOFF.md
```

## 5. Plugin layer

The plugin layer starts only after the MVP contracts are frozen.

### 5.1 Service plugin protocol

A service plugin may observe or extend application-level behavior through explicit hooks:

```python
class ServicePlugin(Protocol):
    plugin_id: str

    def on_run_created(self, run: PublicRunView) -> None: ...
    def on_event(self, event: PublicRunEvent) -> None: ...
    def on_run_terminal(self, run: PublicRunView) -> None: ...
```

Restrictions:

- hooks receive sanitized immutable projections;
- plugins cannot mutate the authoritative run state;
- plugin exceptions are isolated and recorded;
- plugins cannot see Provider credentials;
- hooks have bounded execution time or are dispatched asynchronously.

### 5.2 Optional plugin examples

Not part of MVP completion:

- OpenTelemetry exporter;
- Prometheus metrics;
- authenticated tenant resolver;
- Redis idempotency store;
- distributed queue adapter;
- WebSocket transport;
- webhook notification sink;
- rate-limit policy plugin.

### 5.3 Plugin registry

The first plugin registry should be explicit and static:

```python
registry = ServicePluginRegistry([plugin_a, plugin_b])
```

No dynamic package discovery, arbitrary import strings, or remote plugin installation in v0.12.

## 6. Test matrix

| Area | Required evidence |
|---|---|
| Route validation | invalid task, limits, workspace, IDs |
| Non-blocking API | blocking Fake Engine does not block `/health` |
| Completion | submitted run reaches completed terminal state |
| Failure | executor exception becomes typed public error |
| Cancellation | active blocking Fake Engine becomes stopped |
| Duplicate submit | idempotency key returns same run |
| Conflict | same key + different request returns 409 |
| SSE ordering | sequences are monotonic and terminal is unique |
| SSE resume | `Last-Event-ID` replays missing retained events |
| Backpressure | slow subscriber is bounded/disconnected |
| Security | secret-like values absent from every public payload |
| Compatibility | legacy CLI/TUI/Desktop tests still pass |
| Optional dependency | base import works without FastAPI |

## 7. Delivery sequence

### Segment 0 — Freeze contracts

- inspect current `QueryEngine`, Desktop controller, event reducers, Trace projections, and CLI entrypoints;
- record exact baseline SHA;
- add Handoff in `NOT STARTED`;
- run current non-live baseline.

### Segment 1 — Pure application service

- implement contracts, event buffer, worker execution, state views, cancellation, idempotency, and shutdown;
- test without FastAPI installed.

### Segment 2 — FastAPI adapter and SSE

- add optional dependency;
- implement routes and SSE;
- add HTTP integration tests with Fake Engine.

### Segment 3 — Plugin protocol

- add sanitized observer protocol and static registry;
- prove plugin failures cannot fail a run;
- add one in-memory test plugin.

### Segment 4 — Verification

- focused service tests;
- full non-live regression;
- Ruff;
- live localhost smoke with a disposable Provider credential;
- Handoff and artifacts.

## 8. Non-goals

The MVP does not include:

- distributed workers;
- Redis, Kafka, Celery, or Kubernetes;
- authentication/authorization product policy;
- multi-tenant billing;
- WebSocket parity;
- automatic task resumption after process death;
- replacement of `QueryEngine`;
- streaming Provider tokens;
- arbitrary third-party plugin loading.

## 9. Definition of Done

MVP is complete only when:

- all five routes work;
- a blocking Fake Engine proves the event loop remains responsive;
- SSE ordering, replay, terminal behavior, and backpressure are tested;
- cancellation and idempotency are tested;
- secret non-echo tests pass;
- base installation remains free of FastAPI;
- full non-live regression and Ruff pass;
- live localhost Provider smoke is clearly classified as passed, pending, or blocked.

Plugin phase is complete only when:

- the static registry works;
- all hook payloads are sanitized immutable projections;
- a failing plugin cannot alter the run result;
- plugin behavior is covered by tests.
