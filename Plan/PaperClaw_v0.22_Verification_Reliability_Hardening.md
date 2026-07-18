# PaperClaw v0.22 — Verification Reliability & Semantic Acceptance Hardening

## Status

Development baseline: `main @ 1050392a27784ecd695fb45e2d980e4ce9658ab3`.

This plan is an implementation contract for v0.22. It does not claim the capability is complete until the exact branch head passes the required tests and live-provider evidence is recorded.

## Problem

The v0.18 live Mistral acceptance produced a case where a read-only worker returned an evidence-backed correct analysis but the task was reported failed by the verification path. The existing code has two materially different mechanisms:

1. deterministic `VerificationPlan` / `VerificationResult` checks for files, hashes, command history and post-write verification;
2. model-based Reflection that interprets failed or incomplete evidence.

For read-only tasks, deterministic verification can pass without proving that the returned analysis actually satisfies the task acceptance criteria. The release handoff described the observed failure as a flaky judge rejection, but the current deterministic/read-only control flow does not fully explain that result. v0.22 must make the decision layers explicit and observable before adding retry behavior.

## Goals

1. Preserve deterministic verification as the source of truth for locally checkable evidence.
2. Add a separate semantic acceptance gate for Worker outputs and acceptance criteria.
3. Decouple semantic judge model construction from the execution model path.
4. Add typed semantic outcomes: `passed`, `rejected`, `inconclusive`, `transient_error`, `provider_error`, `protocol_error`.
5. Retry only retryable/transient provider failures within a strict total attempt bound.
6. Confirm semantic rejection with a second judgment; disagreement becomes `inconclusive`, not a hard business failure.
7. Emit bounded, non-secret trace metadata for deterministic and semantic decisions.
8. Account judge model calls in Worker/team budgets.
9. Keep the legacy `Coordinator` and direct Worker behavior compatible; enable semantic acceptance through an explicit composition layer.
10. Add deterministic regression coverage and an opt-in live Mistral acceptance scenario.

## Decision pipeline

```text
Worker execution
  -> deterministic Verify
  -> if deterministic verification failed: no semantic retry; preserve failure
  -> if Worker otherwise completed and semantic judge configured:
       semantic judgment #1
       -> passed: accept
       -> rejected: confirmation judgment #2
            -> rejected: reject
            -> passed: inconclusive
       -> retryable provider failure: bounded retry within total attempt cap
       -> non-retryable provider failure: provider_error
       -> invalid judge contract: protocol_error
  -> map semantic outcome to Worker status
       passed -> completed
       rejected -> failed
       inconclusive/transient_error/provider_error/protocol_error -> blocked
```

## Architecture

### `SemanticJudgeResult`

A serializable result attached to `WorkerResult` with:

- status;
- reason code;
- bounded summary;
- attempt count;
- provider/model identity when available;
- transient flag.

No raw prompt, credentials, hidden reasoning, or unbounded provider response is persisted.

### Judge model factory and Coordinator compatibility

The existing base `Coordinator` constructor is intentionally unchanged. v0.22 introduces a `SemanticCoordinator` composition that accepts an optional `judge_model_factory`, constructs a separate judge model for each Worker, and adds the semantic-judge reserve to conservative model-call budgeting. Direct callers that continue to use the base `Coordinator` retain the pre-v0.22 behavior.

Production composition paths that opt into v0.22 use `ReliableSubagentTaskTool` / `SemanticCoordinator`. The judge factory is separate from the Worker execution `model_factory` and may return a different provider/model.

CLI and Service composition use a dedicated judge model instance and support optional environment overrides:

- `PAPERCLAW_JUDGE_API_KEY`;
- `PAPERCLAW_JUDGE_BASE_URL`;
- `PAPERCLAW_JUDGE_MODEL`;
- `PAPERCLAW_JUDGE_PROVIDER`;
- `PAPERCLAW_JUDGE_TIMEOUT_SECONDS`.

Each value falls back to the corresponding execution-provider setting when not supplied. Desktop currently creates a distinct judge client from the active Desktop Provider configuration; it does not read global judge environment overrides for a per-request credential flow.

### Retry policy

- deterministic evidence failure: no retry;
- semantic rejection: one independent confirmation judgment;
- retriable `ProviderError`: retry while total attempts remain;
- non-retriable provider failure: no retry;
- malformed semantic output: protocol error, no unbounded repair loop.

Total semantic judge calls are capped at two per Worker completion proposal. The underlying judge Provider adapter is configured for one request attempt so Provider retries do not multiply the semantic gate's total attempt budget.

## Implementation sequence

### Phase A — contracts and judge

- add typed semantic result contract;
- implement bounded semantic judge prompt/parser/policy;
- add unit tests for pass, confirmed reject, disagreement, transient retry, provider error and protocol error.

### Phase B — Worker/Coordinator integration

- run semantic acceptance only after deterministic verification allows completion;
- emit `verification.semantic.completed` trace event;
- expose semantic result in `WorkerResult` and compact parent payload;
- count judge calls against Worker/team model-call budgets;
- reserve at most two semantic judge calls in `SemanticCoordinator` scheduling.

### Phase C — composition

- CLI: separate judge model factory with environment overrides;
- Desktop: separate model instance using the current Provider request configuration;
- Service durable tasks: separate judge model factory with environment overrides;
- Durable task executor: optional separate judge model factory, preserving existing store/runtime boundaries.

### Phase D — regression and acceptance

Required automated coverage:

- semantic judge unit tests;
- judge environment configuration tests;
- read-only Worker semantic acceptance regression;
- legacy path without judge factory remains unchanged;
- subagent tool composition and model-call accounting;
- v0.18 Subagent acceptance;
- v0.19 durable tasks;
- v0.20 plan/skills;
- v0.21 LSP;
- full non-live pytest/Ruff;
- Desktop Playwright/package gates through existing workflows.

Required live evidence:

- Mistral read-only two-worker scenario;
- semantic judge metadata captured separately from deterministic verification;
- no Fake/Mock evidence represented as live-provider evidence.

## Non-goals

- replacing deterministic verification with LLM-as-a-judge;
- unbounded self-reflection or majority voting;
- automatic retry of deterministic failures;
- remote workers/distributed queue/PostgreSQL;
- changing the v0.19 durable task source-of-truth semantics;
- changing LSP from read-only to mutating operations.

## Definition of done

v0.22 is complete only when:

- deterministic verification and semantic acceptance are separate contracts;
- judge model construction is independently configurable in CLI/Service and separately instantiated in Desktop;
- semantic outcomes are typed and auditable;
- only transient provider failures receive bounded retries;
- rejection confirmation disagreement produces `inconclusive`;
- judge calls are included in budget accounting;
- read-only analytical tasks receive semantic acceptance when the v0.22 composition is configured;
- legacy callers that use the base `Coordinator` retain existing behavior;
- all required automated gates pass at the exact candidate SHA;
- live Mistral evidence is recorded, or explicitly marked pending/blocked without being misrepresented as automated acceptance;
- final Handoff records exact SHA, CI, evidence boundaries, limitations and next steps.
