# PaperClaw v0.07 Test Hardening Gaps — Test Report

## Status

- Branch: `test/v0.07-hardening-gaps`
- Pull request: `#17` (Draft, not merged)
- Base: `main@ec1ecbeaf37c0e6ea85a07c12446b3d8f9b8e409`
- Result: **OFFLINE GO**

This task is a gap-only continuation after merged PR #13. It does not repeat the Provider matrix, replay corruption suite, 10k Inspector checks, threshold boundaries or Live Replay isolation already accepted there.

## Delivered coverage

### Golden Eval dataset

Frozen scenarios under `tests/fixtures/eval_golden/`:

- completed success;
- provider retry threshold failure;
- tool failure with failed terminal;
- partial non-terminal trace.

The manifest freezes selected metrics, terminal status, `overall_passed` and ordered `failed_checks`.

### Property-based Trace fuzzing

Hypothesis examples per CI run:

- 100 generated valid lifecycle traces;
- 100 generated secret/redaction cases;
- 150 generated sequence-order cases.

The generated lifecycle test exercises:

```text
validate_trace
→ inspect_run_trace
→ replay_recorded_trace
→ evaluate_trace
```

and compares repeated outputs for determinism.

### Local mock collector

A real local `ThreadingHTTPServer` receives requests after the production exporter has already accepted the logical HTTPS endpoint and exact host allowlist.

Covered:

- 200 success and request ID;
- bearer token in header only;
- payload redaction;
- HTTP 400 / 401 / 429 / 500;
- timeout;
- connection failure;
- collector error body excluded from surfaced errors.

No real external collector is contacted.

### Full integration scenario

The integration path executes:

```text
FakeModel
→ AgentRuntimeExecutor
→ real FileWriteTool
→ QueryEngine
→ SessionService / SQLite
→ SQLiteTraceReader
→ Inspector
→ Recorded Replay
→ Eval
→ JSONL export/load
```

Assertions include Run completion, actual workspace write, event cardinality, faithful replay, Eval PASS, JSONL equality, source database SHA256 stability and exclusion of task/file content/path from Trace JSONL.

## CI result

GitHub Actions run `29453571098` / run number `149` on head `a043c7feba619c3d9b6dec4bf4678e002a857412`:

- Windows Server 2025 / Python 3.12;
- pytest call phase: **485 passed, 0 failed, 0 skipped**;
- pytest session exit status: `0`;
- Ruff E9/F63/F7/F82: **PASS**;
- artifact ID: `8358539315`;
- artifact name: `pytest-results-29453571098`;
- artifact digest: `sha256:c9227a78fe502de82d97f6d363bc9971ff5f09aed1410caf67e5c4ffb539b658`.

The pytest counts were independently parsed from `pytest_reportlog.jsonl` rather than inferred only from the job conclusion.

## Production impact

Production source code and public contracts are unchanged. The only dependency change is adding Hypothesis to the `dev` extra.

## Deferred real acceptance

This task intentionally does not execute:

- live Mistral;
- a real external collector;
- live replay;
- mutating live-replay tools;
- real MultiAgent TUI flows from PRs #14–#16.
