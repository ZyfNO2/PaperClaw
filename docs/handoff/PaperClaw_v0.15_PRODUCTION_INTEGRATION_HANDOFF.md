# PaperClaw v0.15 Production Integration & Security Handoff

## Branch and dependency

- Branch: `feat/v0.15-production-integration-security`
- Draft PR: #38
- Parent PR: #37
- Parent verified head: `a44fb89cbef221e1cb591887fca7542e621e1007`
- Validated v0.15 code head: `14362a91dc65899e321ed70da3e3b7de0c8c0e86`

Do not merge #38 before #37. After #37 is merged, rebase or retarget #38 and rerun exact-head CI.

## Runtime flow

```text
POST /v1/runs
  → ServiceRunRequest normalization and digest
  → SQLite durable run + idempotency record
  → worker claim and lease
  → QueryEngine
  → authorization-wrapped ToolRegistry
  → durable runtime events and service metadata
  → terminal state
  → SQLite-backed SSE replay
```

## Important modules

- `src/paperclaw/service/durable_application.py` — base durable execution service.
- `src/paperclaw/service/production_application.py` — cancellation-race hardening used by the public entry point.
- `src/paperclaw/durability/service_store.py` — durable public events and mutable service metadata.
- `src/paperclaw/policy/tools.py` — fail-closed authorization boundary.
- `src/paperclaw/service/fastapi_app.py` — persistent replay and disconnect behavior.
- `src/paperclaw/service/runtime_factory.py` — authorization-wrapped production registry.
- `src/paperclaw/service/resilience.py` — typed timeout contract.

## Operational defaults

- Default database: `~/.paperclaw/service.sqlite3`
- Default disconnect behavior: `detach_on_disconnect`
- Bash and unknown tools: denied without trusted static approval
- SQLite: WAL, foreign keys and busy timeout
- Recovery: first abandoned run without action receipt may requeue; uncertain side effects fail closed to `recovery_required`

## Verified behavior

- full non-live Windows regression: 717 passed;
- Ruff gate: pass;
- Desktop focused tests and Windows packaging: pass;
- cross-Python-process expired-lease reconciliation: covered;
- event replay across service/process recreation: covered;
- pre-runtime cancellation race: covered;
- path-traversal and private-network URL rejection: covered.

## Next acceptance work

1. Merge or otherwise integrate parent PR #37.
2. Rebase/retarget #38 and rerun CI on the resulting exact head.
3. Launch Uvicorn with a real Provider and execute one read-only repository task.
4. Test `detach_on_disconnect` through a real browser/proxy.
5. Test `cancel_on_disconnect` through a real browser/proxy.
6. Kill the service process during a safe read-only run, let the lease expire, restart, and record reconciliation evidence.
7. Attempt a destructive Bash request without approval and record the policy denial.
8. Decide whether trusted Bash approval should remain an environment-only configuration or move to an approval plugin.

## Next plugin order

1. `PrometheusMetricsPlugin` or `OpenTelemetryExporterPlugin`;
2. `ProviderCircuitBreakerPlugin` with explicit retry classification;
3. `RedisStreamsQueuePlugin` while retaining SQLite/PostgreSQL as source of truth;
4. `TenantAuthorizationPlugin` and authenticated run ownership;
5. production BM25/MCP adapters for v0.14 evaluation.

## Release boundary

Keep PR #38 Draft until parent integration and manual Provider/process-kill acceptance are documented. No automatic merge or release is authorized.
