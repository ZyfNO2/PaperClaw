# PaperClaw v0.08 Context Orchestration MVP Handoff

## Repository

- Repository: `ZyfNO2/PaperClaw`
- Base: `main@36f44de6b580ded14ff198d64c1e3d80bbfe3fe7`
- Branch: `feat/v0.08-context-orchestration-mvp`
- Draft PR: `#19`
- Merge state: `not merged`
- PR state: `Draft`
- Implementation code Gate head: `1b563c3959a854c5c7c2e1f6a952edd3c614b415`
- Current status: `offline_validated / closeout CI pending`

## Completed Content

### Context contracts and policy

- `ContextRequest`
- `ContextPolicy`
- `ContextCandidate`
- `ContextSelection`
- `ContextConflict`
- `ContextBudgetAllocation`
- `PromptSection`
- `PromptAssembly`
- `ContextAssemblyTrace`
- `ContextCandidateSource`

### Deterministic orchestration

- collect attributed candidates;
- deterministic deduplication;
- explicit conflict resolution;
- protected-context fail-closed behavior;
- static source quotas and exclusion reasons;
- oversized candidate rejection;
- final rendered-prompt token Gate;
- stable Prompt/policy versions and fingerprint;
- trust-separated rendering;
- bounded, content-free assembly Trace.

### Runtime integration

- opt-in `ContextOrchestratedAgentRuntimeExecutor`;
- existing `AgentRuntimeExecutor` retained as compatibility path;
- `QueryEngine` unchanged;
- assembly immediately before each Provider call;
- assembly events emitted through QueryEngine event flow;
- SQLite assembly events stored in existing `session_events`;
- explicit Context budget failure normalized to `budget_exhausted / context_budget_exhausted`.

### Demo and artifacts

- deterministic cross-domain external-instruction fixture;
- reproducible CLI generator;
- source-controlled JSON artifact with normalized fixture latency;
- implementation summary;
- test report;
- known limitations;
- file manifest;
- SOP and README synchronization.

## Main Files

### Added

- `Plan/PaperClaw_v0.08_Context_Orchestration_MVP_SOP.md`
- `src/paperclaw/context/orchestration.py`
- `src/paperclaw/harness/context_runtime_executor.py`
- `scripts/run_v0_08_context_demo.py`
- `tests/unit/test_context_orchestration.py`
- `tests/unit/test_context_orchestration_budget_edges.py`
- `tests/unit/test_context_runtime_executor.py`
- `tests/integration/test_v0_08_context_assembly_demo.py`
- `tests/integration/test_v0_08_demo_script.py`
- `artifacts/v0_08/*`

### Modified

- `src/paperclaw/context/__init__.py`
- `src/paperclaw/harness/__init__.py`
- `README.md`

## Key Architecture Decisions

1. `QueryEngine` stays a thin lifecycle façade.
2. Context assembly is performed at the model boundary, not in Agent nodes or Tool code.
3. Future Retrieval/Memory/MCP sources return `ContextCandidate` values only.
4. v0.04 persisted Context selection is reused through `ContextBuilder`.
5. External text is always quota-bound and rendered only as untrusted data.
6. Prompt priority does not grant execution permission.
7. `session_events` remains the only durable event fact source.
8. Legacy behavior remains available by using `AgentRuntimeExecutor`.

## Validation

### GitHub Actions code Gate

- Run: `29504198854`
- Head: `1b563c3959a854c5c7c2e1f6a952edd3c614b415`
- Windows pytest: `521 passed, 0 failed, 0 skipped, 0 warnings`
- Ruff high-signal lint: `PASS`
- Report artifact digest: `sha256:6317963d55efef7cb4a2b786b7f7285c38d19ab70d309f295c5106387d9ee287`

The closeout run after committed artifacts and completion checks is recorded below when complete.

### Test classification

The suite exercises real QueryEngine, AgentRuntimeExecutor, SQLite Repository, schema migration, SessionService, filesystem workspaces, ContextBuilder, Orchestrator, Prompt assembly, and durable events. Provider output and external Retrieval are deterministic fakes. This is offline integration validation, not live external-service validation.

## Live or External Validation Not Executed

- live OpenAI-compatible or Mistral call using the v0.08 executor;
- network Retrieval/RAG;
- MCP server connection;
- long-term Memory;
- full MultiAgent Context policy;
- TUI Context panel.

No live test is required to accept the frozen v0.08 MVP. Those capabilities are not claimed as implemented.

## Known Limitations

See `artifacts/v0_08/known_limitations.md`. The most important current limits are:

- opt-in Python executor, no default CLI flag;
- char/4 token estimator;
- static quotas;
- prior-message and current-run state scope;
- no RAG/MCP/long-term Memory;
- no full MultiAgent Context policy;
- no Context Inspector UI.

## Remaining Work

For v0.08 MVP closeout only:

1. complete final closeout CI on the documentation/artifact head;
2. record final CI run, test count, and branch head in this Handoff and `test_report.md`;
3. keep PR #19 Draft and unmerged for owner review.

Post-MVP items are not remaining v0.08 defects. They require separate user authorization and a new SOP.

## Next Developer Steps

1. Open Draft PR `#19` and confirm its head matches this Handoff's latest validated head.
2. Review `Plan/PaperClaw_v0.08_Context_Orchestration_MVP_SOP.md`.
3. Run:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python scripts/run_v0_08_context_demo.py
python .claude/hooks/sop_completion_check.py
```

4. Verify `artifacts/v0_08/mvp_demo_trace.json` remains unchanged after rerunning the demo.
5. Do not merge or mark Ready without owner review.

## Acceptance Decision

`OFFLINE GO` for v0.08 MVP. Final branch closeout remains pending only until the documentation/artifact head receives a successful CI run.
