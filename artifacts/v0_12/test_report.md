# PaperClaw v0.12 Test Report

## Automated evidence

Exact implementation head: `1a225ce5aa5ebcc53729607fda19834cd50e5adf`.

### Full regression

- Workflow: `CI`
- Run: `29614255414`
- Platform: GitHub Actions Windows runner, Python 3.12
- Result: `706 passed`, `0 failed`
- Marker selection: `not real_llm`
- Pytest artifact: `pytest-results-29614255414`
- Artifact ID: `8419962391`
- Artifact digest: `sha256:68e62ef1f89308cdc116cf7cd948d8a6c5765a01b52f6b2111e59c00ddbce499`

### Ruff

- Workflow run: `29614255414`
- Rules: `E9,F63,F7,F82` with existing `F821` compatibility ignore
- Result: PASS

### Focused v0.12 coverage

- completion and terminal reconciliation;
- idempotent resubmission and digest conflict;
- global concurrency rejection;
- cancellation of a blocking Fake Executor;
- monotonic event sequences and bounded retention;
- sequence-based resume;
- public secret-field removal;
- plugin failure isolation;
- FastAPI health, submit, get, conflict and SSE routes.

## Classification

These are offline control-flow, HTTP-adapter and repository-regression tests. They do not constitute a real Provider end-to-end service test.
