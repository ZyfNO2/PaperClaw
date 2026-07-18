# PaperClaw v0.12-v0.14 Backend MVP Handoff

## 1. Status

**Status: MVP IMPLEMENTED / OFFLINE VALIDATED / LIVE INTEGRATION PENDING**

The three planned backend stages and their static plugin boundaries are implemented on one development branch. Automated evidence proves the offline service control flow, SQLite durability semantics, deterministic evaluation pipeline, existing repository regression and desktop packaging compatibility.

This Handoff does not claim real Provider service operation, real process-kill recovery, distributed execution, or production BM25/MCP/Context adapters.

## 2. Repository and delivery references

- Repository: `ZyfNO2/PaperClaw`
- Base branch: `main`
- Documentation baseline: `0fade574e3b26214a0db860ba5513fb676ecb32c`
- Development branch: `feat/v0.12-v0.14-backend-mvp-plugins`
- Draft PR: `#37`
- Verified implementation head: `1a225ce5aa5ebcc53729607fda19834cd50e5adf`
- Merge state: not merged; PR remains Draft.

The implementation branch was created only after the following three documents were committed to `main`:

1. `Plan/PaperClaw_v0.12_Service_API_MVP_and_Plugins.md`
2. `Plan/PaperClaw_v0.13_Durable_Execution_MVP_and_Plugins.md`
3. `Plan/PaperClaw_v0.14_Research_Demo_Eval_MVP_and_Plugins.md`

## 3. v0.12 Service API

### Completed

- FastAPI/Uvicorn optional dependency group.
- `paperclaw api` and `paperclaw-api` entrypoints.
- Thread-backed application service over existing `QueryEngine`.
- Typed request, state, event and public error contracts.
- Process-local concurrency limit.
- Idempotency key + request digest conflict behavior.
- Cooperative cancellation.
- Bounded event history and resumable SSE.
- Environment-backed Runtime factory.
- Secret-safe public projections.
- Static fail-isolated service observer plugins.

### Pending

- real localhost Uvicorn/Provider smoke;
- authentication and tenant policy;
- distributed execution/idempotency;
- integration with v0.13 durable storage.

## 4. v0.13 Durable Execution

### Completed

- SQLite schema for runs, transition journal, leases, idempotency and action receipts.
- Compare-and-swap state transitions.
- Single-winner worker claim.
- Lease renewal and ownership validation.
- Expired-run recovery scanning.
- One safe automatic requeue when no external action receipt exists.
- Fail-closed `recovery_required` behavior for uncertain side effects.
- Deterministic action keys and at-most-once tested callback execution.
- Static fail-closed recovery policy plugins.

### Pending

- real forced process termination/restart acceptance;
- service integration;
- PostgreSQL/Redis adapters;
- MultiAgent durable mailbox;
- compensation for known external actions.

## 5. v0.14 Research Demo & Eval

### Completed

- versioned dataset/result/report contracts;
- deterministic dataset and report digests;
- recorded variants;
- retrieval, claim, citation and operational metrics;
- plugin protocols for retrieval, capabilities, metrics and rendering;
- JSON/Markdown report and comparison CLI;
- canonical no-retrieval and evidence-backed fixtures;
- byte-reproducible artifact generator.

Canonical recorded values:

- dataset digest: `a0156e6d5c73ebde49b753b35ebc3337900897ab0f2c6f16b1e9cfcd94e8d774`;
- report digest: `68a82cc177bbe465515c11e727b9b351469f365de1a31d7e3972f4e0c5bbdbbc`;
- baseline mean Recall@K: `0.0`;
- evidence-backed variant mean Recall@K: `1.0`.

These are deterministic fixture measurements, not live model results.

### Pending

- adapters to the existing BM25, MCP and Context Orchestration implementations;
- live repository experiment;
- larger governed dataset;
- semantic claim/citation evaluation.

## 6. Automated verification

### Full repository regression

- Workflow: `CI`
- Run: `29614255414`
- Exact head: `1a225ce5aa5ebcc53729607fda19834cd50e5adf`
- Platform: Windows, Python 3.12
- Result: `706 passed`, `0 failed`
- Ruff: PASS
- Pytest artifact: `pytest-results-29614255414`
- Artifact ID: `8419962391`
- Digest: `sha256:68e62ef1f89308cdc116cf7cd948d8a6c5765a01b52f6b2111e59c00ddbce499`

### Compatibility smoke

On the preceding implementation head:

- Desktop focused tests: `44 passed`;
- Windows PyInstaller `onedir`: PASS;
- packaged executable and static assets: PASS;
- workflow run: `29613807590`;
- package artifact digest: `sha256:8565d17818e3bd78ccf36971aab1a6422532fb27f3b84303376b9a2a234b6902`.

## 7. Main files

### Service

- `src/paperclaw/service/contracts.py`
- `src/paperclaw/service/application.py`
- `src/paperclaw/service/fastapi_app.py`
- `src/paperclaw/service/runtime_factory.py`
- `src/paperclaw/service/plugins.py`
- `src/paperclaw/service/entrypoint.py`

### Durability

- `src/paperclaw/durability/core.py`
- `src/paperclaw/durability/plugins.py`

### Research evaluation

- `src/paperclaw/research_eval/contracts.py`
- `src/paperclaw/research_eval/metrics.py`
- `src/paperclaw/research_eval/runner.py`
- `src/paperclaw/research_eval/cli.py`
- `scripts/generate_v0_14_canonical.py`

### Tests and fixtures

- `tests/unit/service/`
- `tests/integration/service/`
- `tests/integration/durability/`
- `tests/unit/research_eval/`
- `tests/fixtures/research_eval/`

## 8. Exact next integration steps

1. Wire `RunApplicationService.submit/cancel/terminal` to `SQLiteDurableRunStore` behind an optional durable mode.
2. Add startup reconciliation before accepting HTTP submissions.
3. Add a real subprocess kill/restart acceptance script.
4. Implement a BM25 adapter using the existing v0.09.1 retrieval API.
5. Implement an MCP capability adapter using the existing v0.09 client/runtime contracts.
6. Add one disposable-key localhost Provider service smoke.
7. Keep PR #37 Draft until these live/integration boundaries are reviewed; do not merge automatically.
