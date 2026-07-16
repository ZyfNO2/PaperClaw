# PaperClaw v0.08 Known Limitations

## Current MVP Limits

1. **Opt-in executor only.** `ContextOrchestratedAgentRuntimeExecutor` is a public Python API but is not yet exposed as a default CLI/TUI flag. Existing CLI behavior intentionally remains on `AgentRuntimeExecutor`.
2. **No live Provider acceptance for v0.08.** The assembly boundary is covered with `FakeModel`, SQLite, real filesystem temp workspaces, and full CI. No paid or external Provider call was required or executed for this MVP.
3. **Deterministic fallback estimator.** Token estimates use the conservative `char/4` estimator. Provider tokenizer-specific counting and cache hints are not implemented.
4. **Static source quotas.** Bucket quotas are deterministic configuration values. There is no learned or trace-adaptive weighting.
5. **No required LLM compaction.** v0.08 reuses v0.04 deterministic ContextBuilder/compaction for persisted ContextItems. Other candidates are selected or excluded; they are not summarized by an LLM.
6. **Current-run Tool history only.** Tool result candidates are read from the active Run. Cross-run Tool result retrieval is not implemented.
7. **Prior messages only.** Repository collection excludes messages written under the current Run so the current user task is not duplicated beside the Runtime Prompt. Conversation history from ended Runs is eligible within the configured recent-message limit.
8. **Task and Checkpoint data are current-run scoped.** No long-term Memory or cross-run state merger exists.
9. **Single-Agent runtime integration.** The full MultiAgent shared/private Context policy is deferred. Existing role-scoped ContextBuilder behavior remains covered as a compatibility boundary.
10. **External data remains visible to the model.** Injection containment separates and labels untrusted data; it does not guarantee a model will never follow malicious text. Permission and validation remain mandatory execution-layer controls.
11. **No Context UI.** Selection, exclusion, budget, conflict, and fingerprint data are available in Trace, not yet in a TUI panel.
12. **No generic policy DSL.** Policy is a typed Python dataclass to keep the MVP small and auditable.

## Operational Limits

- The committed demo artifact normalizes `latency_ms` to `0` so it is byte-for-byte reproducible. Real runtime events retain observed assembly latency.
- Assembly failure caused by protected budget overflow is normalized to `budget_exhausted / context_budget_exhausted`. Other runtime, Repository, and Provider failures retain existing classifications.
- The Context-aware model wrapper uses `ContextVar` to isolate concurrent executions within one process. Distributed execution and cross-process Context coordination are out of scope.

## Upgrade Triggers

A Post-MVP item should become a separate SOP only when at least one real failure Trace or downstream user story demonstrates the need. Relevant triggers include:

- repeated token waste across long-running sessions;
- unacceptable recall under static quotas;
- MCP or RAG candidates exceeding current budget policy;
- real Provider tokenizer drift causing budget failures;
- MultiAgent leakage or missing shared/private Context;
- demand for interactive Context inspection;
- a stable long-term Memory use case with deletion, expiry, supersession, and sensitive-data requirements.

## Not Defects

The following are explicit non-goals, not incomplete v0.08 requirements:

- RAG, vector storage, GraphRAG;
- MCP tool discovery or invocation;
- long-term Memory tables;
- Provider Prompt Cache binding;
- automatic Skill generation;
- Web UI or production API;
- default replacement of the legacy executor.
