# PaperClaw v0.18-v0.21 Integration Handoff

## Repository and branch

- Repository: `ZyfNO2/PaperClaw`
- Integration branch: `feat/v0.18-v0.21-release-integration`
- Base main after post-merge repair: `9f138da1be277b6ae4a0d74a2e1f88c4624d53ed`
- Integration contains the stacked v0.18 Subagent, v0.19 durable background tasks, v0.20 Plan Mode/Skills, v0.21 LSP work, plus the independent v0.18 Desktop zh-CN/en i18n branch.

## Included development

### v0.18

- bounded synchronous `delegate_tasks` Subagent delegation;
- fresh Worker context and independent model adapters;
- scoped tools, paths and writable paths;
- DAG dependencies, parallel execution, file leases and cancellation propagation;
- recursive delegation prohibited;
- compact structured result returned to the parent;
- child model/tool usage accounted into the parent budget;
- Desktop/CLI/TUI integration;
- Desktop English/Simplified Chinese projection layer with persisted locale and protected browser asset registration.

### v0.19

- durable SQLite task store and task state machine;
- idempotency, dependency blocking, leases, heartbeat, expired-worker recovery;
- side-effect-aware recovery and `unknown_outcome` terminal handling;
- bounded background supervisor and Provider concurrency semaphore;
- task tools: create/get/list/stop/output;
- Service task APIs and resumable SSE event stream;
- CLI/Desktop/Service parent runtime integration.

### v0.20

- Plan Mode phases and structured plan artifacts;
- explicit approval before mutating tools can execute;
- Plan Guard for file writes, edits and shell execution;
- AskUserQuestion persisted interaction contract;
- Skill discovery, parameter validation and trust tiers;
- remote-untrusted Skills restricted to read-only capabilities;
- CLI/Desktop/Service integration.

### v0.21

- read-only LSP semantic tool surface: diagnostics, definition, references, symbols and hover;
- stdio JSON-RPC framing, request IDs, timeout handling, diagnostics notifications and process lifecycle;
- workspace/path confinement;
- language-server commands sourced from process configuration instead of Agent-controlled arbitrary commands;
- CLI/Desktop/Service integration;
- deterministic fake stdio LSP server fixture committed for protocol-level testing.

## Existing PR lineage

- PR #43: v0.18 isolated Subagent delegation
- PR #44: v0.18 Desktop zh-CN/en i18n
- PR #46: v0.19 durable background task runtime
- PR #47: v0.20 Plan Mode and Skills
- PR #48: temporary integration-only merge of PR #44 content into this release integration branch

All remain separate historical/review units; this integration branch is the consolidated release-validation line.

## Validation status

Verified before this integration:

- post-merge conflict-marker hotfix was merged to `main`;
- conflict-marker scan, full CI, Context/Memory, Desktop Playwright, Desktop package smoke and process acceptance were green on the repaired baseline;
- v0.18 includes dedicated Fake/offline acceptance and a separate live Mistral workflow so Fake evidence is not represented as real Provider E2E.

Still required on this consolidated branch:

1. repository-wide conflict-marker scan;
2. Ruff and full pytest regression;
3. Desktop Playwright including language switching and Provider configuration;
4. v0.18 Subagent offline acceptance;
5. real Mistral two-worker Subagent acceptance;
6. v0.19 durable task focused acceptance including restart/recovery/cancel/SSE replay;
7. v0.20 Plan Mode/Skills focused acceptance;
8. v0.21 fake-stdio protocol/tool tests and at least one real installed LSP server smoke test;
9. Windows Desktop native smoke where applicable.

## Known limits / not verified

- Real Mistral Subagent acceptance is pending until a live Provider run succeeds and evidence is captured.
- v0.21 has the protocol implementation and fake server fixture, but the full dedicated exact-head LSP acceptance workflow and real language-server smoke evidence still need to be completed.
- This branch is not approved for merge to `main` until consolidated exact-head CI and required real tests are complete.

## Next developer steps

1. Work only on `feat/v0.18-v0.21-release-integration` for release-integration fixes.
2. Do not re-merge the historical stacked branches into this branch.
3. Add/fix only missing acceptance tests and integration defects discovered by CI.
4. Preserve explicit distinction between Fake/offline evidence and real Provider/device/LSP evidence.
5. Keep the integration PR Draft until consolidated acceptance is complete.

Suggested local validation:

```bash
git grep -n -E '^(<<<<<<<|=======|>>>>>>>)'
python -m ruff check src tests
python -m pytest -q
```

Status: **PARTIAL / CONSOLIDATED FOR ACCEPTANCE**.
