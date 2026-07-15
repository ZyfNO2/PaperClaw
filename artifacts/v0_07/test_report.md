# PaperClaw v0.07 Trace Foundation — Test Report

## Final offline result

GitHub Actions CI run `29446553046` / run number `110`:

- environment: Windows Server 2025;
- Python project installed editable with dev extras;
- pytest: **405 passed, 0 failed, 0 skipped**;
- Ruff high-signal checks: **PASS**;
- pytest artifact: `pytest-results-29446553046`;
- artifact digest: `sha256:3435040659e0b59ce36aba2c8ecf73add1818f335d89718369b927adb32bcf5e`.

The result was independently counted from `pytest_reportlog.jsonl`, not inferred only from the job conclusion.

## Regression found and fixed

An earlier CI run `29445764680` produced:

- 404 passed;
- 1 failed;
- failing test: `tests/integration/test_v0_05_mvp_demo.py::test_v0_05_mvp_demo`.

Cause: v0.07 initially added provider/model/duration fields to every model event, including FakeModel, which changed the frozen v0.05 deterministic trace artifact.

Correction: model observability metadata is now emitted only when a model explicitly exposes stable `provider` or `model` attributes. Production `OpenAICompatibleModel` opts in; legacy FakeModel snapshots remain unchanged.

## v0.07 coverage

### Unit

- `TraceEvent` schema validation;
- monotonic sequence enforcement;
- terminal ordering enforcement;
- exact secret and credential-field redaction;
- Bearer redaction;
- user-home path normalization;
- JSON-safe payload conversion.

### Integration

- existing SQLite SessionEvent projection;
- canonical terminal mapping;
- atomic JSONL export/load round trip;
- real QueryEngine → AgentRuntimeExecutor → SessionService → SQLite wiring;
- durable `run.started`;
- provider/model/duration metadata when explicitly available;
- secret-containing provider exception redacted before raw SQLite persistence;
- CLI export read-only database hash check;
- structured unknown-Run failure.

## Mistral live attempt

Secret handling precheck:

- secret file exists;
- exactly one HTTPS base URL was found;
- exactly one key-shaped value was found;
- no secret value was printed.

Attempted request:

```text
GET <configured-base-url>/models
Authorization: Bearer <redacted>
```

Result:

```text
URLError
reason_type=gaierror
reason=[Errno -3] Temporary failure in name resolution
```

Classification:

- provider network reachability: **BLOCKED**;
- HTTP request reached Mistral: **NO EVIDENCE**;
- key validity: **NOT VERIFIED**;
- 401/403 response: **NONE**;
- live chat completion: **NOT RUN**.

This is an execution-environment DNS limitation, not a test pass and not evidence of an invalid key.

## Reproduction

Offline:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

Live Mistral:

```powershell
$env:PAPERCLAW_API_KEY = "<secret>"
$env:PAPERCLAW_BASE_URL = "https://api.mistral.ai/v1"
$env:PAPERCLAW_MODEL = "<model-returned-by-/models>"
$env:PAPERCLAW_PROVIDER = "mistral"
python scripts/run_v0_07_mistral_trace_smoke.py
```
