# PaperClaw v0.07 Trace Foundation — Implementation Summary

## Status

- Offline implementation: **GO**
- Windows CI: **PASS**
- Mistral live acceptance: **BLOCKED_BY_EXECUTION_ENVIRONMENT**
- PR: `#5` (Draft, not merged)

The live attempt failed during DNS name resolution before any HTTP response. This does not prove the key is valid or invalid.

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

## Explicitly deferred

- Provider retry and 429/Retry-After policy;
- thinking-only / empty-content normalization;
- Trace Inspector;
- Recorded or live Replay;
- Eval scorers;
- OpenTelemetry/Langfuse/Phoenix exporters;
- a generic plugin manager or plugin installation system.
