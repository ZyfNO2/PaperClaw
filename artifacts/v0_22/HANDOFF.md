# PaperClaw v0.22 Verification Reliability — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

This handoff records the validated implementation state. The PR remains Draft and has not been merged.

## Repository and branch

- Repository: `ZyfNO2/PaperClaw`
- Baseline: `main @ 1050392a27784ecd695fb45e2d980e4ce9658ab3`
- Development branch: `feat/v0.22-verification-reliability`
- Draft PR: `#51`
- Exact validated implementation SHA: `a557860256a7e666ae20d1b0fa33a5711f9dae96`
- Final documentation commit: see the branch/PR head containing this handoff; no implementation code changed after the validated SHA.

## Objective

v0.22 hardens completion verification after the v0.18 live Mistral acceptance exposed that a correct-looking Worker execution could still be reported as failed through an ambiguous verification path.

The implementation separates two different questions:

1. **Deterministic verification** — local evidence such as files, hashes, command history and post-write checks.
2. **Semantic acceptance** — whether a completed Worker result actually satisfies the explicit task objective and acceptance criteria.

The semantic layer does not replace or upgrade failed deterministic evidence.

## Completed implementation

### Typed semantic acceptance

Added:

- `SemanticJudgeResult` / `SemanticJudgeStatus`;
- `SemanticJudgePolicy`;
- `SemanticAcceptanceJudge`;
- statuses: `passed`, `rejected`, `inconclusive`, `transient_error`, `provider_error`, `protocol_error`.

Rules:

- deterministic verification failure is not retried or upgraded by the semantic judge;
- one semantic rejection is not enough for a hard rejection;
- two consistent semantic rejections produce `rejected`;
- reject/pass disagreement produces `inconclusive`;
- retryable Provider failures may retry only within the same strict total-attempt cap;
- non-retryable Provider failures and malformed judge output do not enter an unbounded repair loop;
- a transient Provider attempt followed by one lone rejection is `inconclusive`, not a confirmed business failure.

### Judge model decoupling

Added a separate judge model construction path:

- `SemanticCoordinator` leaves the base `Coordinator` constructor unchanged;
- `ReliableSubagentTaskTool` opts production subagent composition into semantic acceptance;
- judge model instances are separate from execution model instances;
- CLI and Service support optional judge-specific environment overrides:
  - `PAPERCLAW_JUDGE_API_KEY`;
  - `PAPERCLAW_JUDGE_BASE_URL`;
  - `PAPERCLAW_JUDGE_MODEL`;
  - `PAPERCLAW_JUDGE_PROVIDER`;
  - `PAPERCLAW_JUDGE_TIMEOUT_SECONDS`;
- judge settings fall back to execution Provider settings when overrides are absent;
- Desktop creates a distinct judge client from the active per-request Provider configuration.

The underlying judge adapter uses one Provider attempt; semantic retry is owned by the semantic gate so retry layers do not multiply silently.

### Budget accounting

- semantic judge calls count toward Worker/team model-call usage;
- `SemanticCoordinator` reserves at most two semantic judge calls per Worker completion;
- `delegate_tasks` conservative model-call admission now includes Reflection plus semantic-judge headroom;
- live evidence confirms execution and judge calls are both included in child model-call totals.

### Result and trace separation

Worker/task output now exposes separately:

- deterministic verification result;
- semantic acceptance result.

Bounded semantic trace metadata includes:

- status;
- reason code;
- attempt count;
- provider/model identity;
- transient flag.

Raw credentials, hidden reasoning and unbounded Provider responses are not persisted by this semantic result contract.

### Non-proposal halt state-machine fix

Real-provider debugging exposed a latent Verify Gate bug:

- pre-start cancellation, timeout/max-steps and terminal invalid model output previously reused the `done` route;
- with Verify Gate enabled, `done` entered `VerifyDoneProposalNode` even when no `DoneProposal` existed;
- this could raise `AssertionError` during cancellation races.

v0.22 adds an explicit `halt` route:

- only a real model `DoneProposal` uses `done -> Verify`;
- cancellation, timeout, max-steps and terminal invalid output use `halt -> CompletedNode`;
- stable NodeRegistry registration order is preserved.

Regression tests cover pre-start cancellation and terminal invalid output under Verify Gate.

### Evidence-backed Worker completion contract

The first v0.22 live semantic run correctly rejected a Worker that returned only a status sentence (`inspection complete`) despite having inspected useful evidence.

Worker task context now explicitly requires `done.arguments.result` to:

- be self-contained and evidence-backed;
- explicitly address every acceptance criterion;
- cite exact inspected paths and concrete findings for read-only analysis;
- avoid status-only completion summaries;
- avoid unsupported claims.

The semantic judge was not weakened to accept terse outputs.

## Main files changed

### Runtime and contracts

- `src/paperclaw/agent/flow.py`
- `src/paperclaw/agent/nodes.py`
- `src/paperclaw/multiagent/contracts.py`
- `src/paperclaw/multiagent/semantic_judge.py`
- `src/paperclaw/multiagent/semantic_coordinator.py`
- `src/paperclaw/multiagent/reliable_tool.py`
- `src/paperclaw/multiagent/judge_factory.py`
- `src/paperclaw/multiagent/worker.py`
- `src/paperclaw/multiagent/tool.py`
- `src/paperclaw/multiagent/bootstrap.py`
- `src/paperclaw/multiagent/__init__.py`

### Production composition

- `src/paperclaw/desktop/runtime_factory.py`
- `src/paperclaw/service/entrypoint.py`
- `src/paperclaw/tasks/bootstrap.py`
- `src/paperclaw/tasks/subagent.py`

### Tests and CI

- `tests/unit/multiagent/test_semantic_judge.py`
- `tests/unit/multiagent/test_judge_factory.py`
- `tests/unit/multiagent/test_verification_halt.py`
- `tests/real_llm/test_v018_mistral_subagents.py`
- `.github/workflows/v022-verification-reliability.yml`
- `.github/workflows/v022-mistral-live-acceptance.yml`
- `Plan/PaperClaw_v0.22_Verification_Reliability_Hardening.md`

## Automated validation at exact implementation SHA

Validated SHA:

```text
a557860256a7e666ae20d1b0fa33a5711f9dae96
```

All triggered workflows completed with `SUCCESS`:

| Gate | Run | Result |
|---|---:|---|
| Full CI | `29653420983` | SUCCESS |
| Merge conflict marker scan | `29653421000` | SUCCESS |
| v0.16 process acceptance | `29653420980` | SUCCESS |
| v0.18 Subagent acceptance | `29653421034` | SUCCESS |
| v0.19 Durable background tasks | `29653421001` | SUCCESS |
| v0.20 Plan Mode and Skills | `29653421002` | SUCCESS |
| Context and long memory acceptance | `29653421027` | SUCCESS |
| Desktop Playwright | `29653420985` | SUCCESS |
| Desktop package smoke | `29653421011` | SUCCESS |
| v0.22 Verification reliability | `29653420995` | SUCCESS |
| v0.22 Live Mistral semantic acceptance | `29653420999` | SUCCESS |

### Full repository regression

GitHub Actions run: `29653420983`

- Windows pytest: **830 passed, 0 failed** (counted from call-phase records in `pytest_reportlog.jsonl`);
- Ruff high-signal correctness gate: PASS;
- artifact: `pytest-results-29653420983`;
- artifact digest: `sha256:0cd4f6471e9db2409ac104fe11e8e0cd5e45203994b7a490a00d3d8d45e01cdc`.

### v0.22 focused acceptance

GitHub Actions run: `29653420995`

- focused pytest: **28 passed, 0 failed**;
- Ruff `E9/F63/F7/F82`: PASS;
- artifact: `v022-verification-reliability-29653420995`;
- artifact digest: `sha256:8c7923c6043bb71273bf33b0636f2fb5247921335d6a09c4f370760e7e54bfb3`.

Coverage includes:

- first-pass semantic acceptance;
- confirmed two-rejection path;
- judge disagreement -> inconclusive;
- transient Provider retry;
- transient + lone rejection -> inconclusive;
- non-retryable Provider error;
- malformed judge contract;
- separate judge factory/env overrides;
- model-call budget reserve;
- pre-start cancel halt routing;
- terminal invalid-output halt routing;
- evidence-backed Worker completion contract;
- existing subagent and durable task regressions.

## Real Mistral acceptance

Final successful run: `29653420999`

Provider/model:

```text
mistral / mistral-small-latest
```

The workflow used the real repository `MISTRAL_API_KEY` secret and real Provider calls. No credential was committed or written to the evidence artifact.

Final live evidence:

- both Workers: `completed`;
- both semantic judgments: `passed` on attempt 1;
- separate execution models and judge models were instantiated;
- Provider execution-call overlap: **6.554 seconds**;
- elapsed scenario time: **8.911 seconds**;
- child steps: **8**;
- child model calls including judge calls: **10**;
- child tool calls: **10**;
- recursive delegation: `false`;
- context isolation metadata: `fresh_worker_state`;
- parent result was not truncated.

Semantic outcomes:

- `context-compaction`: PASS — cited inspected Context modules and explained bounded compaction behavior;
- `mcp-permissions`: PASS — cited `src/paperclaw/mcp/runtime.py`, explained the permission boundary and a concrete denial path with evidence.

Artifact:

- `v022-live-mistral-semantic-29653420999`;
- digest: `sha256:3c4b3bc60c6368faed321c082cad65efb992a30796d6da63160dd4323fab22a2`.

### Preserved negative live evidence

The failed live runs were retained as diagnostic evidence rather than rewritten as success:

1. `29652976439`
   - semantic gate correctly rejected a terse status-only `context-compaction` result;
   - concurrent `mcp-permissions` exposed the cancellation-to-Verify `DoneProposal=None` assertion bug.
2. `29653297931`
   - the state-machine assertion was gone;
   - `context-compaction` passed semantic acceptance;
   - broad MCP repository exploration exhausted the 8-step live test budget.
3. `29653355060`
   - `context-compaction` again passed;
   - broad MCP search still exhausted a 12-step test budget.
4. `29653420999`
   - live case was scoped to the actual permission-boundary module instead of using step inflation as a discovery benchmark;
   - both Workers and both semantic judgments passed under an 8-step-per-task bounded test configuration.

## Architecture decisions

1. **Deterministic evidence remains authoritative.** Semantic judging cannot turn failed local evidence into success.
2. **Semantic acceptance is explicit and separately typed.** Model disagreement/infrastructure instability is not collapsed into ordinary task failure.
3. **Hard semantic rejection requires confirmation.** One model rejection is insufficient.
4. **Retry is bounded at one layer.** The judge adapter itself uses one attempt; the semantic policy owns the maximum of two total calls.
5. **Legacy base Coordinator remains compatible.** Semantic behavior is enabled through explicit composition rather than silently changing every direct caller.
6. **Non-proposal stops do not enter Verify.** `done` means a real `DoneProposal`; runtime termination uses `halt`.
7. **Live acceptance tests semantic reliability, not autonomous repository discovery.** The MCP live scenario is scoped to the module that actually contains the permission boundary.

## Known limitations

- Semantic acceptance remains model-based. A semantic `passed` result is not proof that the underlying analysis is scientifically or logically true; deterministic evidence and independent review remain separate concerns.
- If `PAPERCLAW_JUDGE_*` overrides are not configured, CLI/Service use a separate client instance but fall back to the same Provider/model configuration as execution.
- Desktop uses a distinct judge client from the active request Provider configuration; it does not independently source global judge credentials because Desktop credentials are request-scoped.
- The semantic policy intentionally allows only two total judge calls. A transient Provider failure can consume confirmation capacity; a later lone rejection becomes `inconclusive` rather than being escalated to a hard rejection.
- The live MCP acceptance is intentionally scoped to `src/paperclaw/mcp/runtime.py`; it does not claim a benchmark for autonomous codebase discovery.
- Repository `README.md` still contains an older capability summary that stops before the v0.18-v0.22 release line. This is pre-existing documentation drift and should be handled as a documentation-only follow-up rather than mixed into this reliability release.

## Not implemented / non-goals

- Remote Worker execution;
- Redis/PostgreSQL distributed queue or store migration;
- Agent message bus;
- majority-vote or unbounded judge ensembles;
- automatic retry of deterministic failures;
- semantic judge authorization to execute tools;
- LSP mutating code actions/rename/workspace edits.

## Next developer steps

1. Review Draft PR #51 without changing it to Ready automatically.
2. Confirm the exact branch head contains this handoff and that `a557860256a7e666ae20d1b0fa33a5711f9dae96` remains its last implementation-code commit.
3. Review the preserved failed live runs alongside final run `29653420999`; do not discard the negative evidence.
4. If accepted, merge PR #51 using the repository's normal owner-controlled process.
5. Start the next feature line from the post-merge `main`, not from historical v0.18-v0.21 branches.

Recommended next version direction after merge:

```text
v0.23 Executor isolation / subprocess Worker foundation
  -> later Remote Worker gateway
  -> later distributed store/queue
  -> later Agent message bus
```

Do not start distributed queue work before the executor boundary is isolated and tested.

## Suggested verification commands

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82
```

Focused v0.22:

```powershell
python -m pytest -q `
  tests/unit/multiagent/test_semantic_judge.py `
  tests/unit/multiagent/test_judge_factory.py `
  tests/unit/multiagent/test_verification_halt.py `
  tests/unit/multiagent/test_subagent_tool.py `
  tests/unit/multiagent/test_subagent_runtime_integration.py `
  tests/unit/tasks
```

Real Mistral validation remains an explicit live test and must use a configured secret rather than committed credentials:

```text
GitHub Actions -> v0.22 Live Mistral semantic acceptance -> workflow_dispatch
```

## Final classification

**COMPLETE**

- implementation complete;
- deterministic automated acceptance complete;
- full repository regression complete;
- real Mistral semantic acceptance complete;
- Draft PR remains unmerged for owner review.
