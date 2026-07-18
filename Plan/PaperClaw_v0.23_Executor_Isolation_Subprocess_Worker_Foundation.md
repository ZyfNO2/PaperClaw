# PaperClaw v0.23 Executor Isolation / Subprocess Worker Foundation

> Status: implementation in progress  
> Stack base: `feat/v0.22-verification-reliability @ 798641e146fbe0cd28b5720aead59b65ab9f601f`  
> Branch: `feat/v0.23-executor-isolation`

## 1. Goal

v0.23 introduces a process-isolation boundary before any Remote Worker, distributed queue/store, or Agent Message Bus work.

Current Coordinator execution is coupled to `WorkerThread`, in-process `Worker` objects, and thread cancellation. The next architecture must instead depend on a stable executor contract so the execution location can later move from:

```text
in-process thread
    -> local subprocess
    -> remote worker gateway
    -> distributed worker fleet
```

without rewriting task/result semantics at each stage.

## 2. Scope

### Included

1. Typed executor contracts independent from Coordinator/Provider implementation.
2. Backward-compatible `InProcessWorkerExecutor` behavior for existing MultiAgent paths.
3. `SubprocessWorkerExecutor` foundation with:
   - spawn-safe process entrypoint;
   - explicit request/result envelopes;
   - PID and lifecycle observability;
   - bounded wait;
   - terminate -> kill escalation;
   - child crash/no-result classification;
   - timeout/cancel classification;
   - JSON-safe error metadata;
   - no raw traceback/secret leakage across the executor boundary.
4. A durable single-Worker subprocess adapter using inherited environment-backed Provider configuration.
5. Opt-in production composition for the durable task path; default remains compatible until the subprocess gate is proven.
6. CI acceptance for success, crash, timeout, cancellation, malformed result, process cleanup, workspace isolation, and legacy compatibility.

### Explicitly excluded

- Remote HTTP/gRPC Worker transport;
- Redis/PostgreSQL queue/store;
- multi-host file lease backend;
- distributed scheduling;
- Agent Message Bus fan-out/routing;
- subprocess execution for parallel write Workers before lease state is externalized;
- arbitrary untrusted Python entrypoints;
- sandbox/container security claims.

## 3. Architectural boundary

```text
Coordinator / Durable Task Runtime
            |
            v
      WorkerExecutor Protocol
       /                \
      /                  \
InProcessExecutor   SubprocessExecutor
                         |
                         v
                 isolated child process
                         |
                  registered entrypoint
                         |
                    Worker runtime
```

The parent owns orchestration decisions. The executor owns only one bounded execution lifecycle.

## 4. Frozen executor contracts

### `ExecutorStatus`

```text
pending
running
succeeded
failed
cancelled
timed_out
crashed
unknown_outcome
```

### `ExecutionRequest`

Required fields:

- `execution_id`
- `task_id`
- `entrypoint`
- `payload`
- `workspace`
- `timeout_seconds`

Rules:

- entrypoint must be explicitly allowlisted by the executor;
- payload must be JSON-serializable;
- workspace must resolve to an existing directory before launch;
- request metadata must not carry secrets.

### `ExecutionResult`

Required bounded evidence:

- `execution_id`
- `task_id`
- `status`
- `output`
- `error_code`
- `error_type`
- `exit_code`
- `pid`
- `started_at`
- `finished_at`
- `termination_method`

No raw child traceback, model prompt, reasoning, Provider response body, or credential crosses this boundary.

## 5. Cancellation semantics

```text
cancel requested
    -> cooperative grace window where supported
    -> process terminate
    -> bounded join
    -> hard kill if still alive
    -> unknown_outcome only when process liveness cannot be proven terminal
```

A terminated child cannot continue producing side effects after the executor reports a terminal result.

## 6. Durable subprocess composition

The first production consumer is the existing durable single-Worker task path because it already enforces `max_agents=1`.

Why this scope is intentional:

- current `LeaseManager` is process-local;
- running multiple subprocess Workers that can write concurrently would falsely imply cross-process lease safety;
- v0.23 therefore does not enable subprocess parallel writers.

The subprocess child reconstructs environment-backed execution/judge models inside the child process and executes the existing durable subagent adapter. Provider credentials are inherited through process environment and are never serialized into the `ExecutionRequest` payload.

## 7. Compatibility

- base `Coordinator` public constructor remains compatible;
- existing direct `Worker` and fake-model tests remain valid;
- default MultiAgent execution remains in-process in v0.23;
- subprocess mode is opt-in for the durable task execution path until acceptance is complete;
- v0.22 deterministic + semantic verification behavior must remain unchanged.

## 8. Acceptance matrix

### Contract tests

- request/result stable JSON serialization;
- invalid workspace rejected before spawn;
- non-allowlisted entrypoint rejected;
- non-JSON payload rejected;
- bounded error normalization.

### Process lifecycle tests

- child success returns output and exit code 0;
- child exception -> `crashed`/typed error without raw traceback;
- child exits without result -> `crashed`;
- timeout -> child is no longer alive;
- cancel -> child is no longer alive;
- terminate escalation is bounded;
- repeated `wait()` is stable/idempotent;
- process resources are closed.

### Durable integration

- subprocess durable task returns the same parent-facing `TaskExecutionResult` contract;
- environment-backed execution/judge model construction occurs inside child;
- cancellation does not leave a live child process;
- subprocess mode does not claim cross-process write-lease safety;
- legacy in-process durable mode remains green.

### Repository regression

- full pytest;
- high-signal Ruff;
- v0.18-v0.22 acceptance workflows;
- Windows spawn-path acceptance.

## 9. GO / NO-GO

### GO

- Coordinator-facing execution lifecycle is represented by an executor contract rather than a concrete thread implementation for the new path;
- subprocess completion/crash/timeout/cancel outcomes are deterministic and bounded;
- no child remains alive after a terminal cancel/timeout result;
- no secret/raw traceback crosses IPC;
- legacy v0.22 behavior remains green;
- full repository CI passes.

### NO-GO

- executor reports cancelled while child is still alive;
- arbitrary untrusted entrypoint import is allowed;
- Provider credentials are serialized into task payloads;
- subprocess parallel writers are enabled with only process-local leases;
- child crash can silently become success or ordinary business failure;
- remote/distributed layers are started before this boundary is stable.

## 10. Follow-on sequence

Only after v0.23 is accepted:

```text
v0.24 Remote Worker Gateway
    -> transport-neutral WorkerExecutor client/server boundary

v0.25 Distributed Store / Queue
    -> external durable task ownership, claim/lease/heartbeat/recovery

v0.26 Agent Message Bus
    -> typed routing, ordering, idempotency, backpressure and audit trace
```

Each follow-on must consume the executor contracts rather than bypassing them.
