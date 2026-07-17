# PaperClaw v0.08 Implementation Summary

## Status

- Version: `v0.08 Context Orchestration / Dynamic Prompt Assembly MVP`
- Baseline: `main@36f44de6b580ded14ff198d64c1e3d80bbfe3fe7`
- Branch: `feat/v0.08-context-orchestration-mvp`
- Draft PR: `#19`
- Validation class: `offline_validated`

## Delivered

1. Added frozen contracts for `ContextRequest`, `ContextPolicy`, `ContextCandidate`, `ContextSelection`, `ContextConflict`, `ContextBudgetAllocation`, `PromptSection`, `PromptAssembly`, and `ContextAssemblyTrace`.
2. Added deterministic `ContextOrchestrator` flow: collect, deduplicate, resolve conflicts, allocate budget, render trust-separated sections, and enforce a final rendered-prompt token Gate.
3. Added `ContextCandidateSource` as the only extension boundary for future Retrieval, Memory, or MCP data. Sources return candidates and cannot mutate Provider input.
4. Added stable Prompt and policy versions plus SHA-256 assembly fingerprint.
5. Added explicit trust ordering and conflict ordering: trust, fact over hypothesis, priority, freshness, stable candidate ID.
6. Added protected-context fail-closed behavior. External untrusted candidates cannot self-promote through `pinned`, `constraint`, L0, or L1 metadata.
7. Added per-bucket quotas and explicit exclusion reasons, including `candidate_too_large`, `bucket_quota:*`, `input_budget`, and `rendered_prompt_budget`.
8. Reused v0.04 `ContextBuilder` and `ContextSnapshot` selection for existing persisted `ContextItem` values instead of creating a second persistent Context pipeline.
9. Added opt-in `ContextOrchestratedAgentRuntimeExecutor`, composed around the existing `AgentRuntimeExecutor`. `QueryEngine` remains unchanged and the legacy executor remains the default compatibility path.
10. Added `context.assembly.completed` and `context.assembly.failed` events. With SQLite enabled, those events are stored in the existing `session_events` fact source without raw Prompt or candidate content.
11. Added deterministic cross-domain injection demo and a source-controlled JSON artifact.

## Architecture Decisions

### Thin QueryEngine

No Context collection, Prompt assembly, Repository reads, RAG, MCP, or Tool execution logic was added to `QueryEngine`. The new behavior is activated only by choosing the v0.08 executor.

### Model-boundary assembly

Assembly occurs immediately before the underlying Provider call through a `ChatModel` wrapper. This covers the existing Decide and Reflection model calls without forking the Agent graph.

### Existing Context reuse

Persisted v0.04 `ContextItem` values are first selected through `ContextBuilder`; selected IDs are then converted into v0.08 candidates. Compaction summaries created by `ContextBuilder` are refetched so selected summaries are not lost.

### Trust-separated rendering

Provider input has stable sections:

1. `RUNTIME PROTOCOL`;
2. `SELECTED CONTEXT`;
3. `UNTRUSTED DATA`.

External content remains visible as data but is wrapped with an explicit non-instruction boundary.

### Durable trace boundary

Durable events contain IDs, hashes, versions, reasons, token counts, conflicts, and bounded aggregate data. They do not contain raw Prompt, raw candidate text, Provider secrets, or hidden reasoning.

## Defects Found and Fixed During Development

1. Demo messages originally used random IDs, causing cross-process fingerprint drift. The fixture now uses a fixed message ID.
2. Oversized candidates were initially charged at a capped token value while rendering full content. They are now excluded unless protected, and rendered Prompt size is checked after section headers and wrappers are added.
3. External candidates could initially mark themselves `pinned` or `constraint`. External untrusted candidates are now always quota-bound.
4. Runtime latency made the committed demo artifact non-reproducible. The source-controlled fixture normalizes `latency_ms` to `0`; live runtime events retain observed latency.

## Scope Deliberately Not Implemented

- RAG or vector database;
- MCP Client or Server;
- long-term Memory lifecycle;
- LLM summarizer as a required dependency;
- automatic Skill generation;
- Provider-specific Prompt Cache integration;
- generic policy DSL;
- full MultiAgent shared/private Context policy;
- Context Inspector UI.

## Evidence

- SOP: `Plan/PaperClaw_v0.08_Context_Orchestration_MVP_SOP.md`
- Demo: `scripts/run_v0_08_context_demo.py`
- Canonical artifact: `artifacts/v0_08/mvp_demo_trace.json`
- Test report: `artifacts/v0_08/test_report.md`
- Handoff: `docs/handoff/PaperClaw_v0.08_Context_Orchestration_MVP_HANDOFF.md`
