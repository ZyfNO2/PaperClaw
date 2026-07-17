# Consolidated PR Final Code Review

## Scope

This review covers the unified development branch that supersedes PRs #34, #35, #36, #37 and #38.

Reviewed areas:

- desktop frontend merge boundaries and console entrypoints;
- manual OpenAI-compatible provider configuration;
- protected loopback browser API;
- FastAPI/SSE service integration;
- SQLite durable run state and event replay;
- worker leases, recovery and cancellation races;
- tool authorization, workspace containment and URL validation;
- public event and metadata redaction;
- test collection, Playwright and Windows packaging compatibility.

## Findings fixed

### CR-01 — Duplicate provider test module basename

The consolidated tree contained two `test_provider_config.py` modules in different test directories. Pytest imported one under the other's module name and aborted collection.

Resolution:

- renamed the desktop-focused module to `test_manual_provider_config.py`;
- retained and expanded the provider behavior coverage.

### CR-02 — Missing capabilities from the alternative provider PR

The final desktop/provider chain did not include two useful behaviors from the superseded alternative implementation.

Resolution:

- added an optional manual model fallback for compatible providers without a usable `/models` endpoint;
- preserved the previous active manual or environment configuration when a reconnect attempt fails;
- marked manually entered/unlisted models as unverified;
- capped the exposed discovered model list.

### CR-03 — Partial provider configuration could mix credentials

A run request containing only part of an explicit provider configuration could be completed with the API key stored in the active manual provider state.

Resolution:

- any explicit provider field now prevents automatic injection of the in-memory manual credential;
- explicit provider configuration remains the responsibility of the existing request validation path.

### CR-04 — Result finalization race could become `runtime_failed`

A cancellation committed between the worker's state read and terminal compare-and-swap could throw a CAS error. The broad exception handler then misclassified the run as a runtime failure.

Resolution:

- added lease-checked atomic terminal finalization in SQLite;
- cancellation deterministically wins when committed first;
- stale workers cannot finalize a run reclaimed by another worker;
- the terminal state, metadata, transition, lease release and final public event are committed in one transaction.

### CR-05 — Crash window between output, terminal state and event

The worker previously persisted result metadata, terminal state and the final event in separate transactions. Process failure inside that window could leave a running run with completed output and permit duplicate recovery execution.

Resolution:

- moved all terminal persistence into the same `BEGIN IMMEDIATE` transaction;
- added deterministic cancellation/finalization and stale-worker tests.

### CR-06 — Run timeout lost its layer-specific error

A cooperative run timeout was represented as an ordinary stopped run and result finalization could overwrite the timeout error.

Resolution:

- a timeout cancellation finalizes as `failed` with `stop_reason=run_timeout`;
- the durable error retains `code=run_timeout`;
- ordinary user cancellation continues to finalize as `stopped`.

### CR-07 — Unbounded no-op drainer scheduling

Every submission queued `max_active_runs` drain tasks even when drainers were already active.

Resolution:

- added explicit drainer slot accounting;
- at most `max_active_runs` drainers are scheduled;
- a finishing drainer rechecks the durable queue to avoid a submission/exit race.

### CR-08 — Cancellation state, reason and events were non-atomic

Queued and running cancellation updated state, metadata and events in separate transactions.

Resolution:

- added atomic cancellation persistence;
- queued cancellation commits stopped state, reason and both public events together;
- running cancellation commits cancelling state, reason and request event while retaining the worker lease.

### CR-09 — Token-shaped secrets were incompletely redacted

Keys such as `access_token` and `refresh_token` were not removed, while token usage counters must remain visible.

Resolution:

- redact keys ending in `_token` or beginning with `token_`;
- preserve non-secret counters such as `input_tokens` and `output_tokens`;
- apply the rule to both public projections and durable event storage.

### CR-10 — URL authorization accepted credential-bearing and ambiguous hosts

The tool policy did not explicitly reject embedded URL credentials, subdomains of `localhost`, or ambiguous integer/hex loopback representations.

Resolution:

- reject URL userinfo;
- reject `*.localhost` and common metadata hostnames;
- reject ambiguous numeric/hex host encodings;
- retain the documented limitation that production DNS-resolution-aware egress enforcement is still required.

### CR-11 — Workspace `.env` values polluted process state

The desktop adapter loaded workspace `.env` values through `os.environ.setdefault`. Switching workspaces could therefore reuse the first workspace's credentials.

Resolution:

- resolve provider values per request without mutating `os.environ`;
- precedence is process environment, selected workspace `.env`, then current-directory `.env`;
- added cross-workspace isolation tests.

## Remaining accepted limitations

- provider and tool call hard interruption adapters remain future plugin work;
- a non-cooperative synchronous executor can outlive a cooperative timeout request;
- DNS rebinding protection and OS-level process/network sandboxing are not implemented;
- authentication, tenant ownership and RBAC are not implemented;
- SQLite remains the single-host reference store;
- real Provider/Uvicorn and manual live-process kill acceptance remain separate from offline CI.

## Review disposition

No known critical or high-severity issue remains in the reviewed offline MVP scope. The PR remains Draft until exact-head CI and any required live acceptance are recorded.
