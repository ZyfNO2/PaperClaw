# PaperClaw v0.08 Context Orchestration MVP Handoff

## Repository

- Repository: `ZyfNO2/PaperClaw`
- Base: `main@36f44de6b580ded14ff198d64c1e3d80bbfe3fe7`
- Branch: `feat/v0.08-context-orchestration-mvp`
- Draft PR: `#19`
- Merge state: `not merged`
- PR state: `Draft`
- First full code Gate head: `1b563c3959a854c5c7c2e1f6a952edd3c614b415`
- Validated closeout head: `b3f56af23de73d7921dc49ee6dda8a0dccb61878`
- Evidence-sync head: `c4eaa5dadb1ad624edbf71ba2af3d4fe43bcf51c`
- Final handoff head: `e9693f9954886068992170344bb93d54e9ab91ff`
- Current status: `OFFLINE GO / waiting owner review`

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
- external self-promotion prevention;
- static source quotas and explicit exclusion reasons;
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

### Demo and closeout

- deterministic cross-domain external-instruction fixture;
- reproducible CLI generator;
- source-controlled JSON artifact with normalized fixture latency;
- committed artifact equality test;
- implementation summary, test report, known limitations, and file manifest;
- SOP and README synchronization;
- closeout acceptance test for SOP checkboxes, artifact package, Handoff, and completion hook.

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
- `tests/integration/test_v0_08_closeout.py`
- `artifacts/v0_08/*`
- `docs/handoff/PaperClaw_v0.08_Context_Orchestration_MVP_HANDOFF.md`

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
9. The committed demo normalizes fixture latency only; live runtime events preserve measured latency.

## Validation

### First full code Gate

- Run: `29504198854`
- Head: `1b563c3959a854c5c7c2e1f6a952edd3c614b415`
- Windows pytest: `521 passed, 0 failed, 0 skipped, 0 warnings`
- Ruff high-signal lint: `PASS`
- Report artifact digest: `sha256:6317963d55efef7cb4a2b786b7f7285c38d19ab70d309f295c5106387d9ee287`

### Closeout Gate

- Run: `29506146021`
- Head: `b3f56af23de73d7921dc49ee6dda8a0dccb61878`
- Windows pytest: `524 passed, 0 failed, 0 skipped, 0 warnings`
- Ruff high-signal lint: `PASS`
- Report artifact: `pytest-results-29506146021`
- Artifact ID: `8378659060`
- Report artifact digest: `sha256:a3f84b3e01908f2d032e0e7ea7ef48465c02d23403962a55f44d1ea102e6ff4f`

### Evidence-sync Gate

- Run: `29506642313`
- Head: `c4eaa5dadb1ad624edbf71ba2af3d4fe43bcf51c`
- Windows pytest: `524 passed, 0 failed, 0 skipped, 0 warnings`
- Ruff high-signal lint: `PASS`
- Report artifact: `pytest-results-29506642313`
- Artifact ID: `8378870851`
- Report artifact digest: `sha256:25c5031a5c0383990a09d32893fc18903ba88bfc6dfef1915e9583fa6814ea2e`

### Final handoff-head Gate

- Run: `29507042546`
- Head: `e9693f9954886068992170344bb93d54e9ab91ff`
- Windows pytest: `524 passed, 0 failed, 0 skipped, 0 warnings`
- Ruff high-signal lint: `PASS`
- Report artifact: `pytest-results-29507042546`
- Artifact ID: `8379033993`
- Report artifact digest: `sha256:2035527539055bc66eea8b8d3e952f31c2199e7222d3c0b4e2f204f136b6d028`

The closeout and final suites verify the canonical JSON artifact, SOP completion, required handoff files, generic hook completeness, and actual hook process execution.

### Test classification

The suite exercises real QueryEngine, AgentRuntimeExecutor, SQLite Repository, schema migration, SessionService, filesystem workspaces, ContextBuilder, Orchestrator, Prompt assembly, durable events, and the completion hook. Provider output and external Retrieval are deterministic fakes. This is offline integration validation, not live external-service validation.

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

No implementation, automated test, artifact, SOP, README, or Handoff item remains for the frozen v0.08 MVP.

Repository administration still requires owner action:

1. review Draft PR `#19`;
2. decide whether to request an independent code review;
3. merge only after owner acceptance;
4. do not start v0.09 automatically.

Post-MVP items are not remaining v0.08 defects. They require separate user authorization and a new SOP.

## Next Developer Steps

1. Open Draft PR `#19` and confirm its current head has green pytest and Ruff checks.
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

`OFFLINE GO` for v0.08 MVP. The PR remains Draft and unmerged by design.
