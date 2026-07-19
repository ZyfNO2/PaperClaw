# PaperClaw v0.23 Executor Isolation / Subprocess Worker Foundation — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

This PR is stacked on the completed v0.22 branch because PR #51 is still Draft and unmerged. No merge or branch deletion was performed.

## Repository state

- Repository: `ZyfNO2/PaperClaw`
- Stack base: `feat/v0.22-verification-reliability @ 798641e146fbe0cd28b5720aead59b65ab9f601f`
- Development branch: `feat/v0.23-executor-isolation`
- Draft PR: `#52`
- Exact validated implementation SHA: `153059cf858fa57a9e73a72eb51c76e107a5c691`
- Plan: `Plan/PaperClaw_v0.23_Executor_Isolation_Subprocess_Worker_Foundation.md`

## Implemented boundary

v0.23 freezes a transport-neutral execution contract and proves it with a real local subprocess implementation.

Implemented contracts:

- `WorkerExecutor`
- `ExecutionHandle`
- `ExecutionRequest`
- `ExecutionResult`
- `ExecutorStatus`

Implemented backend:

- `SubprocessWorkerExecutor`
- `SubprocessExecutionHandle`
- spawn-safe `paperclaw.executor.child_host`
- JSON request/result IPC
- allowlisted logical entrypoint registry

The first production consumer is the durable single-Worker task path through `SubprocessSubagentTaskExecutor`.

## Explicit architecture constraint

The existing parallel MultiAgent `Coordinator` is **not** moved to subprocess execution in v0.23.

Reason:

- current write `LeaseManager` state is process-local;
- parallel subprocess writers would bypass each other's in-memory leases;
- advertising that path as process-safe would be incorrect.

Therefore:

```text
v0.23
  durable single Worker -> optional subprocess isolation
  parallel Coordinator  -> existing in-process execution

v0.25 prerequisite before parallel remote writers
  external task ownership + lease + fencing + recovery
```

This is an intentional safety boundary, not an incomplete migration hidden as success.

## Process lifecycle semantics

### Start

- validates existing workspace directory before spawn;
- validates JSON payload/metadata;
- rejects non-allowlisted entrypoints;
- writes request through JSON, never pickle;
- child is launched in a new process/session boundary;
- stdin/stdout/stderr are excluded from the result protocol.

### Completion

Successful child execution must:

- return a mapping;
- serialize to a JSON object;
- emit an atomic `result.json`;
- exit consistently with the result.

Child exits without a result are typed `crashed`.

Invalid/mismatched child results are typed `crashed`, not silently accepted.

### Cancellation / timeout

```text
terminate process tree
  -> bounded wait
  -> force kill process tree
  -> terminal proof
```

- POSIX: process group `SIGTERM` / `SIGKILL`;
- Windows: real `taskkill /T`, escalating to `/F`;
- clean `cancelled` / `timed_out` is returned only when child termination is proven;
- otherwise status becomes `unknown_outcome`.

`wait(timeout)` does not itself cancel or kill execution.

## IPC security boundary

Executor requests recursively reject credential-shaped field names in payload and metadata, including:

- `api_key`
- `token`
- `access_token`
- `refresh_token`
- `password`
- `secret`
- `authorization`
- `cookie`
- `client_secret`
- `private_key`

Normal accounting fields such as `token_budget` and `input_tokens` remain valid.

Provider credentials for the durable subprocess path are inherited through the process environment and reconstructed inside the child. They are not serialized into `ExecutionRequest`.

The result contract does not persist raw:

- traceback;
- exception message;
- prompt;
- model reasoning;
- Provider response body;
- credential.

## Durable task composition

`get_or_create_task_runtime()` now supports:

```text
executor_mode = inprocess | subprocess
```

Default remains:

```text
inprocess
```

CLI opt-in:

```text
PAPERCLAW_TASK_EXECUTOR_MODE=subprocess
```

Subprocess mode constructs execution and judge models inside the child using the existing environment-backed factories.

The parent-side model factory is not constructed for subprocess mode.

## Side-effect uncertainty

Tasks are conservatively treated as write-capable when they have:

- non-empty `writable_paths`, or
- `file_write`, `file_edit`, or `bash` in allowed tools.

For a write-capable subprocess that is force-cancelled, timed out, or crashes before commit state can be proven:

```text
TaskStatus.UNKNOWN_OUTCOME
side_effect_state = unknown
```

Read-only tasks may map proven termination to ordinary `cancelled`, `timed_out`, or `failed`.

## Main changed files

### Executor foundation

- `src/paperclaw/executor/__init__.py`
- `src/paperclaw/executor/base.py`
- `src/paperclaw/executor/contracts.py`
- `src/paperclaw/executor/entrypoints.py`
- `src/paperclaw/executor/child_host.py`
- `src/paperclaw/executor/subprocess.py`

### Durable integration

- `src/paperclaw/tasks/process_executor.py`
- `src/paperclaw/tasks/subprocess_worker.py`
- `src/paperclaw/tasks/bootstrap.py`

### Tests / CI

- `tests/unit/executor/test_subprocess_executor.py`
- `tests/unit/tasks/test_process_executor.py`
- `tests/unit/tasks/test_executor_mode.py`
- `.github/workflows/v023-executor-isolation.yml`

## Validation

Exact validated implementation SHA:

```text
153059cf858fa57a9e73a72eb51c76e107a5c691
```

GitHub Actions run:

```text
29654846660
```

Results:

- Ubuntu focused executor acceptance: **SUCCESS**
- Windows focused executor acceptance: **SUCCESS**
- task compatibility acceptance: **SUCCESS**
- scoped Ruff correctness: **SUCCESS**
- full Windows non-live repository regression: **SUCCESS**
- full repository correctness Ruff: **SUCCESS**

Machine-readable full regression artifact:

```text
artifact: v023-full-regression-29654846660
digest: sha256:7406992c7040b428f3ed1b62293611731e401acaf14f7addfd866c968ffd3530
call-phase pytest: 850 passed / 0 failed
```

The full regression uses the same important execution contract as canonical repository CI:

- Windows runner;
- repository-local TEMP/TMP;
- `--basetemp`;
- pytest report log;
- `-m "not real_llm"`;
- high-signal Ruff `E9/F63/F7/F82` with canonical `F821` handling.

## Preserved negative evidence

One earlier full-regression attempt failed because the newly added v0.23 workflow initially invoked the entire pytest suite without canonical CI's `-m "not real_llm"` filter.

The focused Linux/Windows executor tests were green in that same development line. The workflow was corrected to match the repository CI contract rather than changing product behavior to hide the failure.

## Known limitations

- This is process isolation, not a security sandbox.
- A subprocess inherits environment variables required by the configured Provider.
- Parallel MultiAgent Workers remain in-process.
- Cross-process file-write leases/fencing are not implemented yet.
- Subprocess durable execution is opt-in, not the default.
- No Remote Worker network transport exists in v0.23.
- No Redis/PostgreSQL distributed ownership store exists in v0.23.
- No Agent Message Bus exists in v0.23.
- JSON-file IPC is a local transport implementation; the contracts are intentionally transport-neutral for v0.24.

## Next stacked development sequence

### v0.24 Remote Worker Gateway

Consume the v0.23 contracts through:

- authenticated client/server transport;
- idempotent `execution_id` submit;
- poll/cancel reconciliation;
- workspace-root policy;
- bounded request/result size;
- transport uncertainty -> fail conservative, never duplicate side effects silently.

### v0.25 Distributed Store / Queue

Externalize:

- durable task ownership;
- atomic claim;
- lease + heartbeat;
- fencing token/generation;
- recovery/requeue rules;
- multi-worker contention tests.

Only after this boundary may parallel remote writers be considered.

### v0.26 Agent Message Bus

Add:

- typed envelope;
- sender/recipient/topic routing;
- ordering and idempotency;
- ack/cursor;
- backpressure;
- durable audit trace.

## Final classification

**COMPLETE**

v0.23 establishes and validates the subprocess/transport-neutral executor foundation without making false claims about distributed ownership or cross-process write safety.
