# PaperClaw v0.23 Executor Isolation / Subprocess Worker Foundation

> Status: implementation complete / acceptance in progress  
> Stack base: `feat/v0.22-verification-reliability @ 798641e146fbe0cd28b5720aead59b65ab9f601f`  
> Branch: `feat/v0.23-executor-isolation`  
> Draft PR: `#52`  
> Frozen implementation SHA: `153059cf858fa57a9e73a72eb51c76e107a5c691`

## 1. Goal

v0.23 introduces a transport-neutral execution contract and a local subprocess implementation before any Remote Worker, distributed queue/store, or Agent Message Bus work.

The existing parallel MultiAgent Coordinator remains coupled to in-process Workers, `WorkerThread`, and a process-local `LeaseManager`. v0.23 deliberately does **not** pretend that this write-concurrency boundary is safe across processes. Instead it freezes a reusable executor contract and proves it first on the existing durable single-Worker path:

```text
Durable single-Worker task
    -> WorkerExecutor contract
    -> local subprocess
    -> Remote Worker Gateway
    -> distributed worker fleet
```

The existing parallel Coordinator stays in-process until task ownership, write leases/fencing, and recovery semantics are externalized.

## 2. Scope

### Included

1. Typed executor contracts independent from Coordinator, Provider, and transport implementation.
2. Existing MultiAgent/in-process behavior preserved unchanged.
3. `SubprocessWorkerExecutor` foundation with:
   - fresh Python child process;
   - explicit JSON request/result envelopes;
   - allowlisted logical entrypoints only;
   - PID and lifecycle observability;
   - bounded wait;
   - process-tree terminate -> kill escalation;
   - child crash/no-result/invalid-result classification;
   - timeout/cancel classification;
   - JSON-safe bounded error metadata;
   - no raw traceback/provider body crossing the executor result boundary.
4. Recursive rejection of credential-shaped request fields before IPC serialization.
5. A durable single-Worker subprocess adapter using inherited environment-backed Provider configuration.
6. Opt-in CLI composition via `PAPERCLAW_TASK_EXECUTOR_MODE=subprocess`; default remains `inprocess`.
7. Conservative `unknown_outcome` handling for force-terminated write-capable tasks.
8. Cross-platform Linux/Windows process-lifecycle acceptance plus exact-head full Windows non-live regression.

### Explicitly excluded

- changing the existing parallel Coordinator to subprocess execution;
- Remote HTTP/gRPC Worker transport;
- Redis/PostgreSQL queue/store;
- multi-host file lease backend or fencing-token store;
- distributed scheduling;
- Agent Message Bus fan-out/routing;
- subprocess execution for parallel write Workers before lease state is externalized;
- arbitrary untrusted Python entrypoints;
- sandbox/container security claims.

## 3. Architectural boundary

Implemented v0.23 boundary:

```text
Durable Task Runtime
       |
       v
WorkerExecutor Protocol
       |
       v
SubprocessWorkerExecutor
       |
       v
fresh child process
       |
       v
allowlisted logical entrypoint
       |
       v
environment-backed single Worker runtime
```

Future composition:

```text
Parallel Coordinator
       |
       |  remains in-process in v0.23
       v
externalized ownership / lease / fencing boundary
       |
       v
WorkerExecutor / Remote Gateway
```

The parent owns orchestration and durable ownership decisions. The executor owns exactly one bounded execution lifecycle.

## 4. Frozen executor contracts

### `WorkerExecutor`

```text
start(ExecutionRequest) -> ExecutionHandle
```

### `ExecutionHandle`

```text
execution_id
pid
poll()
wait(timeout)
cancel(reason)
close()
```

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
- bounded JSON metadata

Rules:

- entrypoint must be explicitly allowlisted by the executor;
- payload/metadata must be JSON objects and reject NaN/non-JSON values;
- workspace must resolve to an existing directory before launch;
- no pickle/arbitrary Python-object transport;
- request payload/metadata recursively reject credential-shaped fields such as `api_key`, `access_token`, `password`, `client_secret`, `private_key`, etc.;
- ordinary accounting fields such as `token_budget` and `input_tokens` remain valid.

### `ExecutionResult`

Bounded evidence:

- `execution_id`
- `task_id`
- terminal `status`
- JSON output
- `error_code`
- `error_type`
- `exit_code`
- `pid`
- `started_at`
- `finished_at`
- `termination_method`
- bounded JSON metadata

No raw child traceback, model prompt, reasoning, Provider response body, or credential is serialized as executor result evidence.

## 5. Child host / IPC

The subprocess transport is deliberately JSON-file based:

```text
parent
  -> request.json
  -> python -m paperclaw.executor.child_host
  -> allowlisted logical entrypoint
  -> atomic result.json
  -> parent
```

Rules:

- no pickle;
- no arbitrary `module:function` import from user/task input;
- production default allowlist contains only `tasks.subagent.env.v1`;
- diagnostic entrypoints are enabled only by explicit test executors;
- stdout/stderr/stdin are not part of the result protocol;
- child exception messages/tracebacks are excluded from IPC because they may contain prompts, file content, or secrets.

## 6. Cancellation and timeout semantics

```text
cancel / timeout
    -> signal process tree terminate
    -> bounded wait
    -> force-kill process tree if still alive
    -> prove child terminal
         | yes -> cancelled / timed_out
         | no  -> unknown_outcome
```

Platform behavior:

- POSIX: new process session + process-group `SIGTERM` / `SIGKILL`;
- Windows: new process group + `taskkill /T`, escalating to `/F`.

A handle never reports clean `cancelled` or `timed_out` while its child is still known alive.

`wait(timeout)` is observational only and does not implicitly kill the child.

## 7. Durable subprocess composition

The first production consumer is the existing durable single-Worker task path because it already enforces `max_agents=1`.

The subprocess child reconstructs:

- execution model via `OpenAICompatibleModel.from_env()`;
- semantic judge via `build_judge_model_from_env()`;
- existing `SubagentTaskExecutor` behavior.

Provider credentials are inherited through the process environment and are not serialized into `ExecutionRequest`.

CLI opt-in:

```text
PAPERCLAW_TASK_EXECUTOR_MODE=subprocess
```

Default:

```text
inprocess
```

Service/Desktop are not silently switched by that CLI environment setting.

## 8. Side-effect uncertainty rule

A force-terminated task is considered write-capable when its task contract contains:

- non-empty `writable_paths`, or
- `file_write`, `file_edit`, or `bash` capability.

For such tasks:

```text
cancel / timeout / crash where committed state cannot be proven
    -> TaskStatus.UNKNOWN_OUTCOME
    -> side_effect_state = unknown
```

Read-only tasks can map proven child termination to ordinary `cancelled`, `timed_out`, or `failed`.

This is intentionally conservative. v0.23 does not claim transactional rollback of arbitrary child side effects.

## 9. Compatibility

- base `Coordinator` public constructor remains unchanged;
- parallel MultiAgent execution remains in-process;
- existing direct `Worker` and fake-model tests remain valid;
- default durable execution remains in-process;
- subprocess mode is explicit opt-in;
- v0.22 deterministic + semantic verification behavior remains unchanged;
- no cross-process lease safety is claimed.

## 10. Acceptance matrix

### Contract tests

- request/result stable JSON serialization;
- invalid workspace rejected before spawn;
- non-allowlisted entrypoint rejected;
- non-JSON/NaN payload rejected;
- nested credential-shaped request fields rejected;
- noncredential token accounting fields remain accepted;
- bounded error normalization.

### Process lifecycle tests

- child success returns output and exit code 0;
- child exception -> `crashed` with error type but no raw message/traceback;
- child exits without result -> `crashed`;
- timeout -> child process tree terminal before clean timeout result;
- cancel -> child process tree terminal before clean cancel result;
- terminate -> kill escalation bounded;
- repeated `wait()` / `cancel()` stable;
- short `wait(timeout)` does not kill child;
- process resources/temp IPC directory cleaned on close.

### Durable integration

- subprocess durable task maps back to the existing parent-facing `TaskExecutionResult` contract;
- environment-backed execution/judge construction occurs inside child;
- parent model factory is not constructed for subprocess mode;
- read-only cancellation remains `cancelled` when termination is proven;
- write-capable cancellation/timeout becomes `unknown_outcome`;
- legacy in-process durable mode remains default and green.

### Repository regression

- focused Linux subprocess acceptance;
- focused Windows subprocess acceptance using real Windows process-tree termination;
- `tests/unit/tasks` compatibility suite;
- high-signal Ruff;
- full Windows `-m "not real_llm"` repository regression using the same temp/report-log contract as canonical CI.

## 11. GO / NO-GO

### GO

- stable transport-neutral execution contracts exist independently of concrete subprocess implementation;
- durable single-worker path can explicitly opt into subprocess isolation;
- subprocess completion/crash/timeout/cancel outcomes are deterministic and bounded;
- no child remains alive after a clean terminal cancel/timeout result;
- arbitrary entrypoint import is impossible through request input;
- credential-shaped fields are rejected before IPC serialization;
- write-capable forced termination fails conservative to `unknown_outcome`;
- legacy v0.22 behavior/full repository regression remains green.

### NO-GO

- executor reports cancelled while child is still alive;
- arbitrary untrusted entrypoint import is allowed;
- Provider credentials are serialized into task payloads;
- subprocess parallel writers are enabled with only process-local leases;
- child crash can silently become success or ordinary verified business failure;
- parallel Coordinator is advertised as process-safe before lease/fencing externalization;
- remote/distributed layers bypass these executor contracts.

## 12. Follow-on sequence

After v0.23 acceptance:

```text
v0.24 Remote Worker Gateway
    -> authenticated transport-neutral WorkerExecutor client/server boundary
    -> idempotent execution_id submit/poll/cancel
    -> workspace-root policy + bounded request/result payloads

v0.25 Distributed Store / Queue
    -> external durable task ownership
    -> atomic claim + lease + heartbeat + fencing token + recovery
    -> remove process-local ownership assumptions before parallel remote writers

v0.26 Agent Message Bus
    -> typed routing
    -> ordering / idempotency
    -> ack / cursor / backpressure
    -> durable audit trace
```

Each follow-on must consume the v0.23 executor contracts rather than bypassing them.
