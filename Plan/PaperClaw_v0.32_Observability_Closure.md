# PaperClaw v0.32 — Team Run / Trace / Eval Closure

## Goal

Close the user-visible loop introduced by v0.31:

```text
paperclaw-team-run
  -> durable Message Bus request
  -> existing Coordinator / Worker / Reviewer
  -> durable SessionEvent trace with one stable run_id
  -> SQLiteTraceReader
  -> paperclaw-observe
```

The version does not introduce another scheduler or another trace database schema.
It projects the existing MultiAgent Message Bus stream into the existing Context
Repository and TraceReader contracts.

## Scope

### P0 — unified identity and durable projection

- deterministic `team_run_id(request_id)` and conversation identity;
- Message Bus decorator that writes successful publishes into SessionEvent rows;
- canonical `run.started`, `run.completed`, `run.failed` terminal vocabulary;
- flatten Coordinator EventEnvelope payloads into TraceEvent-compatible fields;
- preserve request, message, agent, task and team-sequence identity;
- idempotent trace event ids derived from durable Message Bus message ids.

### P0 — Model and Tool observability

- Trace-aware UsageCollector emits `model.started` and `model.completed/failed`;
- provider/model, latency, retries, tokens and estimated cost are persisted;
- observed Worker emits bounded `tool.started` and `tool.completed/failed` facts;
- tool arguments, tool output, prompts and hidden reasoning are not copied into traces.

### P0 — CLI closure

- `paperclaw-team-run --trace-database ...` writes a queryable trace;
- command output includes `run_id` and trace database path;
- `paperclaw-observe --request-id ...` resolves the same Team Run;
- existing `--run-id` behavior remains supported.

### P1 — release truth

- package version becomes `0.32.0`;
- README, CHANGELOG and capability catalog reflect merged v0.31 and v0.32;
- wheel/sdist build and installed entrypoint smoke tests;
- Linux and Windows focused tests;
- separate opt-in live Mistral acceptance.

## Acceptance

### Deterministic

1. one bounded Team Run reaches a terminal state;
2. the existing SQLiteTraceReader reads the resulting run with `require_terminal=True`;
3. aggregate eval reports success, model calls, tokens and cost;
4. a tool-using Worker produces one normalized tool span;
5. `paperclaw-observe --request-id` resolves and renders the run;
6. duplicate Bus event publishes remain trace-idempotent.

### Live provider

1. real OpenAI-compatible provider call;
2. bus-driven observed Coordinator execution;
3. durable terminal trace;
4. aggregate report contains at least one priced or explicitly unpriced model call;
5. no claim of scientific answer quality.

## Explicit limits

- delivery remains at-least-once, not exactly-once;
- trace projection is not yet an atomic Outbox transaction with choreography state;
- a crash after an external side effect still requires tool-level idempotency;
- SQLite proves same-filesystem durability, not multi-host broker semantics;
- cancellation and chaos/failure injection are v0.33 scope;
- PostgreSQL and Redis Streams are v0.34 scope.

## Next stacked versions

1. v0.33 — failure injection, recovery, cancellation, Outbox and idempotency;
2. v0.34 — PostgreSQL + Redis Streams multi-process runtime;
3. v0.35 — Hybrid Retrieval and research-quality evaluation;
4. v0.36 — project-scoped Skills and Connectors.
