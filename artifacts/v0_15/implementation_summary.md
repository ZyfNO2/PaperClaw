# PaperClaw v0.15 Implementation Summary

## Status

**MVP IMPLEMENTED / OFFLINE VALIDATED**

Validated code head: `14362a91dc65899e321ed70da3e3b7de0c8c0e86`.

## Delivered

- `DurableRunApplicationService` joining the v0.12 HTTP application contract to the v0.13 SQLite state machine.
- Durable API submission, request-digest idempotency, queued-run worker claim, lease heartbeat, cancellation and terminal persistence.
- Durable public event stream with monotonic per-run sequence numbers.
- SQLite-backed `Last-Event-ID` replay that survives service recreation and process restart.
- Explicit `detach_on_disconnect` and `cancel_on_disconnect` request policies.
- Typed queue, provider, tool, run and graceful-shutdown timeout configuration.
- Enforced queue timeout and whole-run timeout with layer-specific codes.
- Race-hardened cancellation when a stop request arrives before QueryEngine publishes its runtime run ID.
- Fail-closed tool authorization before execution.
- Tool risk levels: read-only, workspace-write, external-write and destructive.
- Workspace path-containment checks.
- SSRF controls for loopback, private, link-local, reserved and metadata-service targets.
- Static trusted approval requirement for destructive service tools.
- Service `QueryEngine` composition now receives an authorization-wrapped registry.
- `paperclaw-api` now defaults to the durable SQLite service path and accepts `--database`.
- Cross-Python-process restart/reconciliation smoke coverage.

## Architecture decision

SQLite is the single-host source of truth for run state, idempotency, leases, service metadata and public event replay. In-memory conditions are wake-up optimizations only. The model can request a tool call, but only the deterministic policy layer can authorize it.

## Plugin boundaries frozen by the plan

- queue backends, including a future Redis Streams adapter;
- tool risk, approval, tenant and network-egress policies;
- provider circuit breaker, fallback, rate-limit and budget policies;
- OpenTelemetry, Prometheus and JSON-log exporters;
- PostgreSQL and external checkpoint/event storage adapters.

## Not claimed

- distributed exactly-once execution;
- arbitrary restoration of an in-flight Provider connection or child process;
- production OAuth/RBAC or multi-tenant isolation;
- Redis queue implementation;
- real Provider request through a manually launched Uvicorn process;
- manual OS kill of a live Provider/tool execution.
