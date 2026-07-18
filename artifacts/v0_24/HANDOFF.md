# PaperClaw v0.24 Remote Worker Gateway — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

- Repository: `ZyfNO2/PaperClaw`
- Stack base: `feat/v0.23-executor-isolation @ b1e28fd76e0ed05bf6098f29283c6ef71854f566`
- Branch: `feat/v0.24-remote-worker-gateway`
- Draft PR: `#53`
- Exact validated implementation SHA: `46414e4aeb5cc8063093180dd7a60c27811344ac`
- Plan: `Plan/PaperClaw_v0.24_Remote_Worker_Gateway.md`

## Delivered

v0.24 carries the v0.23 executor lifecycle across an authenticated HTTP boundary without introducing distributed-queue claims.

### Core

- `WorkerGatewayService`
- `RemoteWorkerExecutor`
- `RemoteExecutionHandle`
- `WorkerGatewayTransport`
- direct transport for contract tests
- stdlib `HttpWorkerGatewayTransport`
- FastAPI/Uvicorn gateway adapter
- standalone `paperclaw-worker-gateway`

### Safety / correctness

- process-lifetime idempotent `execution_id` submit;
- canonical request digest normalized across transport representations;
- same ID + different request conflict;
- used IDs never evicted during process lifetime;
- capacity exhaustion rejects new IDs rather than weakening idempotency;
- workspace-root policy before executor start;
- v0.23 allowlisted entrypoints preserved;
- bearer token kept out of `ExecutionRequest`;
- constant-time bearer comparison;
- bounded streaming request read and bounded response read;
- URL-safe execution identity for HTTP paths;
- remote snapshot binding to execution/task/request digest;
- cancel transport uncertainty -> `UNKNOWN_OUTCOME` + reconciliation required;
- no automatic uncertain rerun.

## Important limit

The idempotency guarantee is **Gateway-process lifetime only**.

After Gateway restart, v0.24 has no durable ownership/idempotency registry and therefore does not claim exactly-once or durable reconciliation. v0.25 must externalize these records before remote execution can be described as restart-safe or distributed-safe.

Parallel remote writers are also not claimed safe; cross-worker ownership/lease/fencing remains v0.25 scope.

## Validation

GitHub Actions run:

```text
29655660206
```

Exact implementation SHA:

```text
46414e4aeb5cc8063093180dd7a60c27811344ac
```

Results:

- Ubuntu gateway focused: SUCCESS
- Ubuntu real localhost Uvicorn roundtrip: SUCCESS
- Windows gateway focused: SUCCESS
- Windows real localhost Uvicorn roundtrip: SUCCESS
- v0.23 subprocess regressions: SUCCESS
- focused Ruff: SUCCESS
- full Windows non-live repository regression: SUCCESS
- repository correctness Ruff: SUCCESS

Machine-readable regression evidence:

```text
870 passed / 0 failed
artifact: v024-full-regression-29655660206
digest: sha256:9f0ac2f84192a786b14ee75ed20bc10a59a804047f1243196af604a57b82a2d0
```

## Preserved negative evidence

Development surfaced and fixed:

1. FastAPI local dynamic `Request` annotation resolution failure caused by postponed annotations.
2. HTTP transport digest mismatch for semantically equal `10` vs `10.0` timeout values; canonical request normalization now precedes hashing.
3. terminal-record eviction could have allowed an old `execution_id` to execute again; replaced by fail-closed capacity exhaustion.
4. raw HTTP `request.body()` bounded only after full allocation; replaced with streamed bounded accumulation.
5. remote snapshots originally checked only execution/task IDs; now also bind to canonical request digest.
6. path-ambiguous execution IDs are rejected at the HTTP boundary.

## Main files

- `src/paperclaw/executor/gateway.py`
- `src/paperclaw/executor/http_gateway.py`
- `src/paperclaw/executor/__init__.py`
- `src/paperclaw/service/worker_gateway_entrypoint.py`
- `tests/unit/executor/test_worker_gateway.py`
- `tests/unit/executor/test_worker_gateway_http.py`
- `tests/unit/executor/test_worker_gateway_http_identity.py`
- `tests/integration/test_worker_gateway_http_e2e.py`
- `.github/workflows/v024-remote-worker-gateway.yml`
- `pyproject.toml`

## Next line

### v0.25 Distributed Store / Queue

Required before distributed writers:

- durable execution/idempotency identity;
- store protocol independent from SQLite implementation;
- atomic ownership claim;
- lease + heartbeat;
- monotonic fencing token/generation;
- stale owner rejection on start/heartbeat/side-effect/complete/requeue;
- recovery rules for expired leases and uncertain side effects;
- multi-process / multi-worker contention evidence;
- only claim real multi-host distribution if an external shared database adapter is actually validated.

### v0.26 Agent Message Bus

After ownership semantics are stable:

- typed durable envelope;
- routing;
- ordering/idempotency;
- ack/cursor;
- backpressure;
- audit trace.

## Final classification

**COMPLETE**

PR remains Draft and unmerged.
