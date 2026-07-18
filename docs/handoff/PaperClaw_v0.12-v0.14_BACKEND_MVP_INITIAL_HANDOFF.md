# PaperClaw v0.12-v0.14 Backend MVP Initial Handoff

## Status

**Status: IMPLEMENTED / AUTOMATED VERIFICATION PENDING**

This branch implements the first complete offline development pass for three consecutive backend stages:

- v0.12 optional FastAPI/SSE service adapter and service observer plugins;
- v0.13 SQLite durable execution, leases, recovery classification, action receipts, and recovery policy plugins;
- v0.14 recorded repository-research evaluation datasets, deterministic metrics, comparison reports, and static plugin protocols.

No live Provider result, process-kill smoke, or production deployment is claimed in this initial Handoff. GitHub Actions results must be attached before the status can advance.

## Repository and branch

- Repository: `ZyfNO2/PaperClaw`
- Documentation baseline on `main`: `0fade574e3b26214a0db860ba5513fb676ecb32c`
- Development branch: `feat/v0.12-v0.14-backend-mvp-plugins`
- Merge policy: Draft PR only; do not merge automatically.

## Implemented scope

### v0.12

- Pure Python `RunApplicationService` over synchronous `QueryEngine`.
- Bounded thread-pool execution.
- Global concurrency limit.
- Request-digest idempotency and conflict detection.
- Cooperative cancellation.
- Bounded replayable public event buffer.
- Secret-like field removal from service projections.
- Optional FastAPI routes and resumable SSE using `Last-Event-ID`.
- Environment-backed Runtime factory.
- Static, fail-isolated service observer plugin registry.

### v0.13

- SQLite schema for durable runs, transition journal, leases, idempotency records, and action receipts.
- Compare-and-swap state transitions.
- Single-winner queued-run claim using `BEGIN IMMEDIATE`.
- Worker lease renewal and ownership validation.
- Startup recovery candidate scan.
- Default fail-closed recovery policy.
- One automatic requeue only when no action receipt exists.
- Uncertain external side effects become `recovery_required`.
- Deterministic action keys and at-most-once tested callback execution.
- Static recovery policy registry that fails closed.

### v0.14

- Versioned JSONL dataset and result contracts.
- Canonical dataset digest and report digest.
- Recorded result variants.
- Recall@K, MRR, required/forbidden claim, citation, unsupported-claim, latency and call-count metrics.
- Isolated metric plugins.
- Explicit retrieval/capability/renderer plugin protocols.
- JSON and Markdown reports.
- Report comparison CLI.
- Canonical evidence-backed and no-retrieval fixtures.

## Verification currently included

- v0.12 unit tests for completion, idempotency, conflict, cancellation, concurrency, event bounds, resume sequences, secret removal, and plugin failure isolation.
- v0.12 FastAPI/TestClient integration test for health, submit, idempotency conflict, state and SSE.
- v0.13 integration tests for CAS, parallel claim, leases, restart reconciliation, action receipt deduplication, uncertain side effects and plugin failure.
- v0.14 unit tests for dataset determinism, known metric values, plugin isolation, failure preservation, CLI report generation and report comparison.

## Pending verification

- GitHub Actions full non-live pytest.
- GitHub Actions Ruff correctness gate.
- Localhost Uvicorn smoke with a Fake Engine.
- Real Provider HTTP service smoke.
- Real process-kill/restart durable recovery smoke.
- Integration of durable state into the live v0.12 service execution path.
- Direct adapters from v0.14 to existing BM25, MCP and Context Orchestration modules; this first pass freezes the evaluation contracts and recorded-run path.

## Known limitations

- Service state remains in memory in v0.12; v0.13 persistence is implemented as a separate reference component and is not yet wired into service submission.
- SSE uses bounded retained events but does not implement a distributed consumer cursor store.
- Concurrency limit is process-local.
- Action receipts provide at-most-once behavior only for code paths that use `IdempotentActionExecutor`.
- Durable recovery cannot resume an in-flight Provider HTTP request or arbitrary child process.
- Evaluation fixtures are deterministic recorded evidence, not live benchmark results.
- Retrieval, MCP and Context plugin protocols are present, but production adapters are a subsequent integration slice.

## Next exact steps

1. Open a Draft PR to trigger full CI.
2. Fix all test, packaging, import and Ruff failures against exact PR head.
3. Generate versioned implementation/test/known-limitations artifacts from the verified head.
4. Add live/manual evidence separately without exposing credentials.
5. Keep the PR Draft until CI is green and the verification boundary is reviewed.
