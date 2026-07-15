# PaperClaw v0.07 Trace Foundation MVP — Handoff

## Repository state

- Repository: `ZyfNO2/PaperClaw`
- Base: `main@725e8a81425efa987f59a6f66ce0021fe7978261`
- Branch: `feat/v0.07-trace-foundation-mvp`
- Pull request: `#5` (Draft)
- Merge status: not merged
- Overall status: **MVP_OFFLINE_GO / LIVE_ACCEPTANCE_BLOCKED**

## Scope delivered

v0.07 establishes a small durable Trace read contract over the existing SQLite SessionEvent log:

1. versioned `TraceEvent` v1;
2. strict per-Run integrity validation;
3. durable `run.started`;
4. canonical Run terminal projection from existing `flow.stopped` facts;
5. read-side Repository and read-only SQLite readers;
6. deterministic atomic JSONL export/load;
7. unified JSON-safety and credential redaction;
8. pre-persistence secret redaction for runtime adapter events;
9. opt-in provider/model/duration observability metadata;
10. `paperclaw trace export` CLI;
11. repeatable Mistral live smoke runner.

No second Trace database, Replay executor, Eval engine, Inspector UI, external observability SDK or generic plugin system was added.

## Important architecture decisions

### One durable fact source

`session_events` remains authoritative. TraceEvent is a stable projection, not a duplicate write model.

### Legacy terminal compatibility

The database continues to store `flow.stopped`. Trace readers project it to `run.completed`, `run.failed` or `run.stopped` based on `stop_reason`, retaining `source_event_type` in payload.

### Secret boundary

Provider secrets are redacted before event observer/persistence and again during Trace projection/export. Tests verify that a secret embedded in a provider exception is absent from raw SQLite.

### Backward-compatible model metadata

Only models that explicitly expose stable `provider` or `model` attributes receive observability metadata and durations. This avoids changing frozen FakeModel event snapshots from v0.05.

## Validation

### Final code-bearing CI baseline

GitHub Actions run `29446553046` / run number `110` on commit `8c9e7e3252c5062a037c2d9e736df53fef3f5e3a`:

- Windows Server 2025;
- pytest: `405 passed`, `0 failed`, `0 skipped`;
- Ruff high-signal checks: PASS;
- pytest artifact ID: `8355781984`;
- artifact digest: `sha256:3435040659e0b59ce36aba2c8ecf73add1818f335d89718369b927adb32bcf5e`.

A final documentation-head CI run should be checked before changing the PR from Draft.

### Regression corrected

Earlier run `29445764680` found one v0.05 deterministic artifact mismatch. The implementation was corrected rather than rewriting the historical artifact. Final run 110 passed all 405 tests.

### Mistral live result

A real authenticated `/models` request was attempted using the supplied local key file. It failed at DNS resolution:

```text
URLError → socket.gaierror → [Errno -3] Temporary failure in name resolution
```

No HTTP response was received. Key validity remains unknown. This is recorded in `artifacts/v0_07/live_smoke/blocker_report.md` and must not be described as live PASS.

## Main files

### Runtime/API

- `src/paperclaw/trace/contracts.py`
- `src/paperclaw/trace/redaction.py`
- `src/paperclaw/trace/reader.py`
- `src/paperclaw/trace/exporter.py`
- `src/paperclaw/trace/__init__.py`
- `src/paperclaw/harness/agent_runtime_executor.py`
- `src/paperclaw/models/adapters/openai_compat.py`
- `src/paperclaw/cli.py`

### Tests

- `tests/unit/test_trace_foundation.py`
- `tests/unit/test_trace_cli.py`
- `tests/integration/test_trace_sqlite_export.py`
- `tests/integration/test_trace_runtime_wiring.py`
- `tests/integration/test_trace_secret_boundary.py`

### Operations/docs

- `scripts/run_v0_07_mistral_trace_smoke.py`
- `Plan/PaperClaw_v0.07_Trace_Foundation_MVP_SOP.md`
- `artifacts/v0_07/implementation_summary.md`
- `artifacts/v0_07/test_report.md`
- `artifacts/v0_07/known_limitations.md`
- `artifacts/v0_07/file_manifest.txt`
- `artifacts/v0_07/live_smoke/blocker_report.md`
- `README.md`

## Reproduction

### Offline

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

### Export a persisted Run

```powershell
paperclaw trace export `
  --database paperclaw.db `
  --run-id <run-id> `
  --output trace.jsonl
```

### Live Mistral

```powershell
$env:PAPERCLAW_API_KEY = "<secret>"
$env:PAPERCLAW_BASE_URL = "https://api.mistral.ai/v1"
$env:PAPERCLAW_MODEL = "<model returned by /models>"
$env:PAPERCLAW_PROVIDER = "mistral"
python scripts/run_v0_07_mistral_trace_smoke.py
```

## Deferred sequence

1. v0.07.1 Provider Reliability;
2. v0.07.2 read-only Trace Inspector;
3. v0.07.3 Recorded Replay without side effects;
4. v0.07.4 Eval scorers;
5. external exporters and live replay only after the above contracts stabilize.

## Next action

Run the final branch-head CI after documentation commits. If it passes, keep PR #5 unmerged and either:

- rerun the Mistral script in a network-enabled environment, then mark live acceptance PASS; or
- review/merge with explicit acknowledgment that offline MVP is accepted while live provider acceptance remains blocked.
