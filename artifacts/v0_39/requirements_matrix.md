# v0.39 SPEC → Implementation → Test Matrix

This matrix records the implementation against the v0.39 Durable Memory,
Context Snapshot and Resume SPEC. The existing v0.39 structured Memory work is
extended in place; no parallel Memory, Prompt, Trace, Task, Artifact or
Multi-Agent runtime is introduced.

| SPEC requirement | Existing seam / implementation | Evidence | Status |
|---|---|---|---|
| Ordered durable `SessionEvent` with schema/version links | `context.contracts.SessionEvent`, `context.repository.SQLiteRepository`, migration v5 | `tests/unit/test_v039_durable_runtime_contracts.py`, `test_context_contracts.py` | offline_validated |
| Atomic sequence allocation and append idempotency | `append_event_with_auto_sequence`, `(run_id, idempotency_key)` unique index, `BEGIN IMMEDIATE` | cross-connection concurrent append contract test | offline_validated |
| Memory provenance and source linkage | existing `MemoryItem.source_refs` plus typed `MemorySourceRef`, legacy source locators | Memory contract/service and legacy import tests | offline_validated |
| Explicit conflict decision | `MemoryConflictDecisionRecord` and existing immutable/tombstone Memory history | conflict decision contract test; Memory tests | offline_validated |
| Deterministic Context Builder and priority policy | existing `ContextOrchestrator`/`PromptAssembler`, explicit `ContextPolicy.priority_order` | Context orchestration tests; v0.08 demo artifact equality | offline_validated |
| Token budget and bounded omissions | existing quota/budget/fit gate; snapshot `input_tokens` and `omitted_counts` | Context budget regression tests; runtime snapshot test | offline_validated |
| Atomic Tool call/result groups | existing repository events grouped before Context selection | tool group contract test | offline_validated |
| Durable `ContextSnapshot` manifest | existing `context_snapshots` extended additively with model, event, artifact, memory and policy locators | runtime snapshot test and v4 migration test | offline_validated |
| Crash/restart reconstruction | `SessionService.reconstruct` over ordered events, task states and snapshots | resume contract tests; existing Context/Session tests | offline_validated |
| Safe resume and terminal no-op | `SessionService.resume`; permission mode preserved; no Tool replay | safe/ambiguous/terminal resume contract tests | offline_validated |
| Unknown external side effect requires manual review | unmatched `tool.started` → `manual_review_required` and durable blocked event | ambiguous Tool resume contract test | offline_validated |
| Trace events / redacted operator projection | existing SessionEvent→Trace projection plus context/memory/session events; operator returns manifests and event metadata | trace tests; operator contract test | offline_validated |
| CLI/operator inspection | existing `session_commands.SessionOperator` and `paperclaw session inspect/context/resume` | operator contract test; CLI parser path | offline_validated |
| v4 backward-compatible migration | additive migration v5; legacy file Memory imported idempotently without rewriting files | v4→v5 migration and legacy import tests | offline_validated |
| Unit / deterministic integration / regression | focused contract tests, existing Memory/Context/Trace tests, full non-live suite | commands recorded in `test_report.md` | partial: two pre-existing Bash tests fail locally |
| Exact-head CI evidence | workflow inspected; branch/commit was not pushed, so no exact-head GitHub run exists | no remote run for final SHA | AWAITING REAL TEST |
| Real LLM / Docker / native manual OS | outside offline v0.39 implementation gate | not run | NOT VERIFIED |

## Deliberate deviations

- The repository canonical field remains `conversation_id`; `SessionEvent.session_id`
  is a compatibility alias, and operator/API surfaces use `session_id` wording.
- The existing Context orchestration buckets are retained and ordered through a
  policy tuple. The implementation does not create a second Prompt Stack.
- The CLI requires an explicit `--database` path so inspection cannot silently
  select an unrelated workspace database.
