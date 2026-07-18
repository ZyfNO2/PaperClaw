# PaperClaw v0.24 Remote Worker Gateway

> Status: implementation in progress  
> Stack base: `feat/v0.23-executor-isolation @ b1e28fd76e0ed05bf6098f29283c6ef71854f566`  
> Branch: `feat/v0.24-remote-worker-gateway`

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

The gateway is an execution transport. It is **not** a distributed queue, scheduler, lease store, or message bus.

## 2. Included

- transport-neutral gateway service contract;
- authenticated HTTP adapter;
- `RemoteWorkerExecutor` + remote execution handle;
- idempotent `execution_id` submit;
- duplicate request digest conflict detection;
- submit / poll / cancel lifecycle;
- bounded request/result payload sizes;
- workspace-root allow policy enforced on the worker host;
- constant-time bearer-token verification;
- terminal result caching for reconciliation;
- conservative network uncertainty handling;
- focused direct-service + HTTP adapter tests;
- full repository regression.

## 3. Excluded

- Redis/PostgreSQL queue ownership;
- worker discovery/load balancing;
- multi-host write leases;
- fencing tokens;
- automatic rescheduling after an uncertain remote execution;
- TLS termination/certificate management;
- arbitrary remote code upload;
- Agent Message Bus.

## 4. Gateway state

A gateway execution snapshot has:

```text
execution_id
task_id
request_digest
state = running | terminal
pid
created_at
updated_at
result?   # ExecutionResult only when terminal
```

The service stores only bounded request identity/digest plus active handle or terminal result. It must not retain credentials.

## 5. Submit idempotency

`execution_id` is the idempotency key.

- first submit -> starts one server-side execution;
- same execution_id + same canonical request digest -> returns existing snapshot;
- same execution_id + different digest -> conflict;
- network retry may safely resubmit the same exact request;
- the gateway never creates a second execution for the same execution_id.

## 6. Workspace policy

Remote execution paths are interpreted on the worker host.

The gateway is configured with explicit allowed workspace roots. A request workspace must resolve under one configured root before execution starts.

No root match -> reject before child spawn.

## 7. Authentication

Execution endpoints require:

```text
Authorization: Bearer <shared gateway token>
```

Rules:

- token is configured out-of-band/environment;
- token is never placed in `ExecutionRequest`;
- verification uses constant-time comparison;
- missing/invalid token -> 401;
- health endpoint may remain unauthenticated.

This is an application authentication baseline, not a replacement for TLS.

## 8. Payload bounds

Default hard bounds:

- request JSON: <= 1 MiB;
- result JSON: <= 4 MiB;
- IDs/error metadata remain bounded by v0.23 contracts.

Oversize input is rejected before execution. Oversize terminal output fails closed as a typed gateway failure instead of streaming unbounded data into the parent.

## 9. Transport uncertainty

The client must not turn a network failure into ordinary business failure.

Rules:

- failed submit response is reconcilable by reusing the same `execution_id`;
- poll transport failure raises typed remote transport uncertainty;
- cancel transport failure returns/raises an uncertain outcome, never claims the remote process stopped;
- no automatic duplicate side-effect execution is allowed.

## 10. HTTP API

```text
GET  /health
POST /v1/executions
GET  /v1/executions/{execution_id}
POST /v1/executions/{execution_id}/cancel
```

`POST /v1/executions` accepts the canonical v0.23 `ExecutionRequest` object.

## 11. GO / NO-GO

### GO

- v0.23 executor contracts unchanged;
- authenticated same-request resubmit is idempotent;
- conflicting execution_id reuse is rejected;
- server workspace-root enforcement occurs before start;
- request/result bounds enforced;
- remote cancel cannot falsely claim termination during transport uncertainty;
- direct and HTTP adapter tests green;
- full repository regression green.

### NO-GO

- gateway accepts arbitrary module/function execution;
- credentials are serialized inside ExecutionRequest;
- retry can start duplicate execution_id instances;
- network error becomes `succeeded`/ordinary `failed` without reconciliation;
- remote writers are described as distributed-safe before v0.25 ownership/fencing exists.

## 12. Follow-on

```text
v0.25 Distributed Store / Queue
  -> external ownership + atomic claim + lease + heartbeat + fencing + recovery

v0.26 Agent Message Bus
  -> typed durable routing + ordering + idempotency + ack/cursor + backpressure
```
