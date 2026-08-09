# PaperClaw v0.39 — Durable Memory, Context Snapshot & Resume SPEC / SOP

## 1. Objective

Upgrade the existing v0.17 memory/context foundation into a durable runtime state model where every model invocation has an explainable context snapshot and a session can be reconstructed after interruption.

This is an extension of existing `FileMemoryStore`, runtime history compaction and Trace. It is NOT permission to replace them wholesale.

## 2. Problem statement

Current foundations already provide bounded human-readable long memory and deterministic prompt compaction, but the interview-grade runtime story still needs a durable link across:

```text
session -> ordered events -> artifacts/evidence -> memory sources
       -> context snapshot -> model/tool actions -> terminal/resume state
```

A runtime must be able to answer:

1. What exactly was known before this model call?
2. Which memory/evidence/event caused that context?
3. Which data was omitted or compacted due to budget?
4. Can the session be reconstructed after process death without inventing state?
5. Can a conflicting memory be superseded without deleting provenance?

## 3. Existing implementation to inspect first

Before changing code, inspect at minimum:

- `src/paperclaw/memory/store.py`;
- `src/paperclaw/context/runtime_compaction.py`;
- `src/paperclaw/agent/prompts.py`;
- `src/paperclaw/agent/state.py`;
- existing Trace/event persistence and service task persistence;
- artifact/evidence stores already present in PaperClaw;
- `tests/unit/context/test_runtime_history_compaction.py`;
- `tests/unit/memory/**`;
- current service/desktop/TUI runtime construction paths.

If current `main` has newer abstractions than this document, use verified repository state and update the Handoff with the deviation.

## 4. Required domain contracts

### 4.1 SessionEvent

Provide or reuse a durable ordered event record with at least:

```text
event_id
session_id
sequence
turn_id | null
event_type
payload / payload_ref
created_at
idempotency_key | null
schema_version
```

Requirements:

- sequence is monotonic per session;
- duplicate idempotency keys return the existing logical append result;
- concurrent append cannot produce duplicate sequence numbers;
- unknown event versions fail explicitly or are safely ignored only when documented;
- events are append-only; corrections are represented by later events.

### 4.2 MemorySource / provenance

Extend current memory semantics so a durable memory can identify why it exists.

At minimum support source references to one or more of:

```text
session_event
artifact
retrieval evidence
operator/user confirmation
imported legacy FileMemoryStore entry
```

A memory projection must expose:

```text
memory_id
scope: user | project | task
content
category
confidence
status
created_at
updated_at
source_refs[]
```

Do not store secrets. Preserve existing privacy rejection.

### 4.3 Memory conflict decision

Represent conflict resolution explicitly with one of:

```text
keep_both
supersede
merge
reject_candidate
```

A superseded memory remains auditable but is excluded from default prompt selection.

Do not silently overwrite provenance-bearing memory.

### 4.4 ContextSnapshot

Immediately before a model call, persist a snapshot manifest containing enough information to reconstruct the context policy decision without storing unbounded duplicate text.

Minimum fields:

```text
context_snapshot_id
session_id
model_call_id
system_prompt_hash / static_prefix_hash
selected_memory_ids[]
selected_artifact/evidence locators[]
event_range / selected event ids
compaction summary reference
omitted/truncated counters
estimated or exact input tokens
policy/config fingerprint
created_at
```

If the provider request body is already safely persisted elsewhere, link it rather than duplicating it.

### 4.5 Context Builder policy

Implement one deterministic ordering policy, configurable but stable by default:

```text
1. system/static prefix
2. project/user durable context
3. active task state
4. selected memory
5. evidence/artifact references
6. compacted historical context
7. recent complete tool-call/tool-result groups
8. current user turn
```

Hard rule: a tool call and its corresponding tool result are an atomic context group for truncation/compaction. Never retain an orphaned result or a call requiring a result that was dropped.

Policy must expose:

- total token budget;
- per-section budget or priority;
- tokens before/after compaction;
- omitted item counts;
- selected memory/evidence ids;
- deterministic fingerprint.

### 4.6 Resume state

Provide a reconstruction function/service that rebuilds session runtime state from durable facts.

Resume MUST:

- detect terminal sessions and avoid re-executing them;
- find the last durable completed boundary;
- preserve request/task idempotency;
- never blindly re-run an external side-effecting tool whose outcome is recorded as unknown;
- classify ambiguous tool outcome as `manual_review_required` or an existing equivalent;
- preserve or tighten the original permission/sandbox policy;
- emit trace events for resume start/result.

## 5. Required runtime/trace events

Reuse the existing Trace vocabulary where possible. Add only the missing event types, for example:

```text
session.event.appended
memory.candidate.created
memory.decision.recorded
context.build.started
context.compaction.completed
context.snapshot.persisted
session.resume.started
session.resume.reconstructed
session.resume.blocked
```

Payloads must be bounded and avoid secrets/full unbounded tool output.

## 6. Storage and migration

Preferred approach: reuse the repository's existing SQLite migration/persistence patterns for structured session/event/source/snapshot facts while preserving `MEMORY.md` / `USER.md` as a human-readable compatibility/projection surface where feasible.

Requirements:

- backward-compatible migration for existing workspaces;
- no destructive rewrite of existing memory files;
- importer/migrator from legacy entries if structured memory becomes authoritative;
- deterministic migration test;
- corruption must fail with a typed error, not silently reset state.

## 7. CLI/operator acceptance surface

Provide a minimal inspect/resume surface using existing CLI patterns, e.g. equivalent to:

```bash
paperclaw session inspect SESSION_ID
paperclaw session context SESSION_ID --latest
paperclaw session resume SESSION_ID
```

Exact command names may follow current CLI architecture.

Operator output should show identifiers and policy decisions, not secret raw prompts by default.

## 8. Tests

### Unit

Cover at least:

- ordered concurrent event append;
- duplicate idempotency key;
- memory provenance round trip;
- supersede/merge/keep-both decision behavior;
- secret rejection remains intact;
- context priority under a tiny token budget;
- tool call/result pair preservation;
- stable context policy fingerprint;
- context snapshot linkage;
- terminal session resume is no-op;
- interrupted safe boundary resumes;
- ambiguous side-effect outcome blocks automatic resume.

### Integration

Create a deterministic fake-model scenario:

```text
user task
 -> context build
 -> tool call
 -> durable event/result
 -> simulated process interruption
 -> new runtime instance
 -> resume
 -> terminal state
```

Assert no duplicate completed tool action and a complete trace/snapshot chain.

### Regression

Run existing context, memory, service, desktop/TUI compatibility suites touched by the change plus full non-live repository regression.

## 9. Acceptance gates

- [ ] existing v0.17 memory behavior remains readable/backward compatible;
- [ ] events have monotonic sequence and idempotent append;
- [ ] every instrumented model call links to one ContextSnapshot;
- [ ] memory selected into context has source provenance or explicit legacy provenance;
- [ ] conflicting memory decisions are explicit and auditable;
- [ ] token policy never splits a tool call/result pair;
- [ ] crash/restart integration test reconstructs state without duplicate safe completed work;
- [ ] ambiguous side-effect state does not auto-replay;
- [ ] focused tests pass on Linux and Windows where current CI supports both;
- [ ] full non-live regression passes;
- [ ] exact-head CI evidence and Handoff are recorded.

## 10. Non-goals

- autonomous memory quality claims without benchmark evidence;
- vectorizing all memory;
- deleting the human-readable memory surface merely for schema purity;
- cross-user cloud memory service;
- exactly-once external side effects;
- new multi-agent scheduling behavior.

## 11. Required implementation SOP

1. Inspect current `main`, existing Plan/Handoff and current tests; record actual reusable seams.
2. Create an isolated feature branch from current `main`.
3. Write/update tests for the first storage/event contract before wiring prompts.
4. Add schema/migration and event repository with idempotency/concurrency coverage.
5. Add provenance/conflict projection while preserving legacy memory behavior.
6. Refactor Context Builder minimally around existing prompt/compaction code; do not create a second prompt stack.
7. Persist ContextSnapshot at the model-call boundary.
8. Add resume reconstruction at an existing runtime/task lifecycle seam.
9. Add CLI/operator inspection after the domain/runtime path works.
10. Run focused tests, full non-live regression, lint/type/build gates used by current repository.
11. Run any real-provider/manual acceptance separately and label it accurately.
12. Fix discovered regressions, then create final implementation commit(s) and `artifacts/v0_39/HANDOFF.md`.

## 12. Stop conditions

Stop and mark `BLOCKED` only if implementation requires an unavailable real provider, OS-level behavior, external service or permission after all offline work is complete. Do not stop merely because the migration or resume logic is extensive.

## 13. Safe interview claim boundary

Safe after acceptance:

> PaperClaw reconstructs model context from ordered durable state, provenance-linked memory and bounded history, persists a context manifest before model invocation, and can resume interrupted sessions from a safe durable boundary without silently replaying ambiguous external side effects.

Do not claim exactly-once execution.
