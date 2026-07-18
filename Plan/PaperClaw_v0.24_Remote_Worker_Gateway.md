# PaperClaw v0.24 Remote Worker Gateway

> Status: implementation complete / acceptance complete  
> Stack base: `feat/v0.23-executor-isolation @ b1e28fd76e0ed05bf6098f29283c6ef71854f566`  
> Branch: `feat/v0.24-remote-worker-gateway`  
> Draft PR: `#53`  
> Validated implementation SHA: `46414e4aeb5cc8063093180dd7a60c27811344ac`

## 1. Goal

Carry the v0.23 `WorkerExecutor` lifecycle across an authenticated network boundary without changing `ExecutionRequest` / `ExecutionResult` semantics.

```text
caller
  -> RemoteWorkerExecutor
  -> authenticated GatewayTransport
  -> WorkerGatewayService
  -> allowlisted server-side WorkerExecutor
  -> subprocess Worker
```

The gateway is an execution transport. It is **not** a distributed queue, scheduler, durable ownership store, multi-host write lease system, or message bus.

## 2. Implemented

- transport-neutral `WorkerGatewayService`;
- `RemoteWorkerExecutor` / `RemoteExecutionHandle`;
- direct test transport + stdlib HTTP transport;
- FastAPI/Uvicorn HTTP gateway service;
- standalone `paperclaw-worker-gateway` command;
- bearer-token auth with constant-time comparison;
- worker-host workspace-root allow policy;
- process-lifetime `execution_id` idempotency;
- same ID + different canonical request digest conflict rejection;
- canonical request normalization before digesting, so transport-equivalent values such as `10` and `10.0` share one identity;
- snapshot binding to `execution_id + task_id + request_digest` on submit/poll/cancel;
- URL-safe HTTP execution IDs;
- streamed raw request-body bounds and bounded client response reads;
- request/result size limits;
- capacity fail-closed behavior that preserves used execution-ID tombstones;
- network cancel uncertainty -> `unknown_outcome`, never false `cancelled`;
- real localhost HTTP process acceptance on Linux and Windows;
- full Windows non-live repository regression.

## 3. Explicit non-goals

- Redis/PostgreSQL queue ownership;
- cross-restart durable idempotency;
- worker discovery/load balancing;
- multi-host write leases/fencing;
- automatic rescheduling after uncertain remote execution;
- TLS termination/certificate management;
- arbitrary remote code upload/import;
- Agent Message Bus.

## 4. Idempotency contract

`execution_id` is the idempotency key **for the lifetime of one Gateway service process**.

- first submit -> starts one server-side execution;
- same ID + same canonical digest -> returns existing running/terminal snapshot;
- same ID + different digest -> conflict;
- used IDs are not evicted;
- when `max_execution_records` is exhausted, new IDs are rejected instead of deleting old tombstones;
- retrying the exact same request after a lost response is safe while the same Gateway process retains the record.

Cross-Gateway-restart idempotency is **not claimed** in v0.24. Durable execution identity/reconciliation moves to v0.25 external storage.

## 5. Workspace and execution policy

Remote workspace paths are interpreted on the worker host. Every request must resolve beneath an explicitly configured workspace root before execution starts.

The server still uses the v0.23 allowlisted executor entrypoint boundary; the Gateway does not accept arbitrary Python module/function execution.

## 6. Authentication

Execution endpoints require:

```text
Authorization: Bearer <shared gateway token>
```

- token is configured out-of-band through `PAPERCLAW_WORKER_GATEWAY_TOKEN`;
- token never enters `ExecutionRequest`;
- verification uses `hmac.compare_digest`;
- missing/invalid auth -> 401;
- health endpoint is public.

This is an application auth baseline, not a replacement for TLS.

## 7. Payload / protocol bounds

Defaults:

- raw execution request body <= 1 MiB;
- terminal result <= 4 MiB;
- cancel body <= 16 KiB;
- HTTP execution ID: `[A-Za-z0-9_.:-]{1,200}`.

Server request bodies are consumed as bounded streams; oversize input is rejected before JSON materialization completes. Client response reads are capped even when `Content-Length` is absent or wrong.

Unknown top-level HTTP request fields are rejected rather than silently excluded from the idempotency digest.

Oversize terminal output fails closed as `gateway_result_too_large`.

## 8. Transport uncertainty

- submit transport failure is not converted to business failure; caller may reconcile with the same execution ID;
- poll transport failure raises typed `GatewayTransportError`;
- cancel transport failure/unconfirmed response returns `UNKNOWN_OUTCOME` with `reconciliation_required=true`;
- snapshots with mismatched execution/task/request digest are rejected as protocol/transport failures;
- no automatic duplicate rescheduling is performed.

## 9. HTTP API

```text
GET  /health
POST /v1/executions
GET  /v1/executions/{execution_id}
POST /v1/executions/{execution_id}/cancel
```

## 10. Validation

Validated implementation SHA:

```text
46414e4aeb5cc8063093180dd7a60c27811344ac
```

GitHub Actions run:

```text
29655660206
```

Results:

- Ubuntu gateway unit acceptance: SUCCESS
- Ubuntu real Uvicorn HTTP roundtrip: SUCCESS
- Windows gateway unit acceptance: SUCCESS
- Windows real Uvicorn HTTP roundtrip: SUCCESS
- v0.23 subprocess regression on both platforms: SUCCESS
- focused Ruff: SUCCESS
- full Windows `-m "not real_llm"` regression: SUCCESS
- repository correctness Ruff: SUCCESS

Machine-readable full regression:

```text
870 passed / 0 failed
artifact: v024-full-regression-29655660206
digest: sha256:9f0ac2f84192a786b14ee75ed20bc10a59a804047f1243196af604a57b82a2d0
```

## 11. GO / NO-GO

### GO

- authenticated same-request resubmit is process-lifetime idempotent;
- conflicting ID reuse is rejected;
- capacity pressure cannot resurrect a used ID;
- workspace policy executes before child start;
- raw request/result bounds are enforced;
- remote snapshots bind to canonical request identity;
- transport uncertainty never becomes false business success/failure;
- real HTTP + subprocess roundtrip works on Linux/Windows;
- full regression is green.

### NO-GO

- claim exactly-once across Gateway restart;
- claim distributed-safe remote writers before external ownership/fencing;
- accept arbitrary code entrypoints;
- serialize credentials inside execution payloads;
- automatically rerun uncertain side effects.

## 12. Follow-on

```text
v0.25 Distributed Store / Queue
  -> durable execution identity
  -> external task ownership
  -> atomic claim + lease + heartbeat + fencing + recovery
  -> cross-process / cross-worker contention evidence

v0.26 Agent Message Bus
  -> typed durable routing
  -> ordering + idempotency
  -> ack/cursor + backpressure
  -> audit trace
```
