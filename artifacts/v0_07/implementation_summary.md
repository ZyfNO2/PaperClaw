# PaperClaw v0.07 Trace Foundation — Implementation Summary

## Status

- Offline implementation: **GO**
- Windows CI: **PASS**
- OpenCode live Provider acceptance: **PASS** (`deepseek-v4-flash`)
- Real-model Live Replay: **PASS** (no-tool, `file_write`, and PowerShell backend)
- HTTPS loopback collector: **PASS**
- PR stack: `#5` through `#11`, with final hardening in `#13`

The supplied OpenCode-compatible configuration completed a real model call and
persisted/exported a four-event durable Trace. The API key was absent from both
SQLite and JSONL. Mistral-specific behavior remains outside this acceptance
because the user selected the already configured OpenCode provider instead.

## Delivered

### Stable Trace contract

`paperclaw.trace.TraceEvent` defines schema version 1 with stable run identity, monotonic sequence, event type, component, status, optional span/provider/model/duration/error metadata, and a JSON-safe payload.

`validate_trace()` rejects:

- non-positive or non-increasing sequence values;
- mixed Runs or Conversations;
- unsupported schema versions;
- multiple canonical terminal events;
- any event after terminal;
- missing terminal when required.

### Single durable source

The existing SQLite `session_events` table remains the only durable event source. v0.07 adds a read-side projection rather than a second Trace database or dual-write transaction.

`AgentRuntimeExecutor` now persists a durable `run.started`. Existing `flow.stopped` records are retained in SQLite and projected to one stable terminal event:

- `run.completed`;
- `run.failed`;
- `run.stopped`.

The projected payload retains `source_event_type=flow.stopped` for auditability.

### Readers and JSONL

- `RepositoryTraceReader` reads an already-open Repository;
- `SQLiteTraceReader` opens an existing database with `mode=ro` and `PRAGMA query_only=ON`;
- `export_trace_jsonl()` writes deterministic JSONL atomically;
- `load_trace_jsonl()` performs schema and trace-integrity validation.

### Redaction boundary

`TraceRedactor` handles known credential fields, exact active provider secrets, Bearer values, user-home paths, bytes, long strings, dataclasses, dates, collections and non-finite floats.

Runtime adapter events are sanitized before they reach the QueryEngine observer or SQLite SessionEvent storage. Export performs defensive redaction again.

The implementation does not persist prompts, HTTP headers, complete provider responses or hidden model reasoning as Trace payloads.

### Provider metadata

Production model adapters may expose stable `provider` and `model` attributes. Model completion/failure events then include provider, model and duration. Legacy models and FakeModel fixtures that do not opt in keep their historical event payload, preserving deterministic v0.05 artifacts.

`OpenAICompatibleModel` accepts an optional provider name and reads `PAPERCLAW_PROVIDER` from the environment, defaulting to `openai-compatible`.

### CLI

```powershell
paperclaw trace export `
  --database paperclaw.db `
  --run-id <run-id> `
  --output trace.jsonl
```

The command is read-only, does not migrate or create the database, requires a terminal event by default and returns a structured JSON summary/error.

### Live runner

`scripts/run_v0_07_mistral_trace_smoke.py` performs a real Mistral call when configured, persists the Run, exports/reloads JSONL and checks provider metadata, terminal integrity and key absence from SQLite/JSONL/summary.

## Follow-on slices implemented on the v0.07 contract

- v0.07.1 bounded Provider Reliability policy and normalized metadata;
- v0.07.2 read-only Trace Inspector;
- v0.07.3 side-effect-free Recorded Replay;
- v0.07.4 deterministic Trace Eval;
- v0.07.5 guarded HTTPS JSON exporter;
- v0.07.6 explicitly authorized Live Replay into a separate target Run.

These remain separate modules and do not introduce a generic PluginManager.
Live Mistral, a real collector and real replay tool execution remain pending.
