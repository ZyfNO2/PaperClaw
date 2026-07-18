# PaperClaw v0.18-v0.21 Corrective Acceptance Handoff

## Repository and release line

- Repository: `ZyfNO2/PaperClaw`
- Main integration commit reviewed: `7b7de6e92eb2325f2fed57785cc0ed53814dd1c0`
- Corrective branch: `fix/v0.18-v0.21-corrective-acceptance`
- Corrective PR: #50
- Exact validated code SHA: `7a9cca7d2c1a3290b857a46009c26318fa04c81d`
- PR #50 remains Draft and must not be merged until the remaining live-provider acceptance is reviewed.

## Included capabilities

### v0.18

- bounded synchronous `delegate_tasks` Subagent delegation;
- fresh Worker context and independent model adapters;
- scoped tools, paths and writable paths;
- DAG dependencies, parallel execution, file leases and cancellation propagation;
- recursive delegation prohibited;
- compact structured result returned to the parent;
- child model/tool usage accounted into the parent budget;
- Desktop/CLI/TUI integration;
- Desktop English/Simplified Chinese projection layer with persisted locale.

### v0.19

- durable SQLite task store and task state machine;
- idempotency, dependency blocking, leases, heartbeat and expired-worker recovery;
- side-effect-aware recovery and `unknown_outcome` terminal handling;
- bounded background supervisor and Provider concurrency semaphore;
- task tools: create/get/list/stop/output;
- Service task APIs and resumable SSE event stream;
- CLI/Desktop/Service parent runtime integration.

### v0.20

- persistent Plan Mode phases and structured plan artifacts;
- explicit approval before mutating tools can execute;
- Plan Guard for file writes, edits and shell execution;
- AskUserQuestion persisted interaction contract;
- Skill discovery, parameter validation and trust tiers;
- remote-untrusted Skills restricted to read-only capabilities;
- CLI/Desktop/Service integration.

### v0.21

- read-only LSP semantic tools: diagnostics, definition, references, symbols and hover;
- stdio JSON-RPC framing, request IDs, timeout/error handling and diagnostics notifications;
- workspace/path confinement;
- language-server commands sourced from process configuration instead of Agent-controlled commands;
- dead language-server detection and restart;
- fresh-generation diagnostics waiting after `didOpen`/`didChange`;
- deterministic fake stdio protocol coverage plus a real local `python-lsp-server` (`pylsp`) semantic smoke test;
- CLI/Desktop/Service integration.

## Corrective fixes after the main integration review

1. **LSP diagnostics freshness**
   - diagnostics now wait for a newer diagnostics generation after a document update instead of returning stale cached results.

2. **LSP process recovery**
   - cached dead language-server clients are detected and recreated.

3. **Dedicated v0.21 acceptance**
   - added fake stdio protocol/tool tests for diagnostics refresh, definition, references, hover, symbols, timeout, confinement and restart;
   - added real local `pylsp` smoke coverage;
   - added `.github/workflows/v021-lsp.yml`.

4. **Desktop i18n event-loop starvation**
   - replaced self-triggering microtask refresh behavior with coalesced macrotask refresh;
   - the MutationObserver is disconnected while applying translations and reattached afterward;
   - SCRIPT/STYLE/NOSCRIPT text is excluded from dynamic translation.

5. **Desktop browser acceptance harness**
   - Playwright now exercises the real modular static assets through a deterministic local HTTP origin instead of `document.write`/`set_content` inlining;
   - Provider E2E assertions were aligned with the current DOM/API contract.

6. **v0.18 acceptance environment**
   - the Subagent acceptance gate runs on Windows, matching the PowerShell-backed local command runtime.

7. **v0.19 concurrency test reliability**
   - concurrency is proven by overlapping execution intervals rather than a machine-speed wall-clock threshold.

8. **Windows package verification**
   - package smoke now verifies `index.html`, `styles.css`, `provider-config.css`, `i18n.js`, `provider-config.js`, and `app.js` are present in the packaged onedir artifact.

## Automated acceptance result

Exact validated code SHA: `7a9cca7d2c1a3290b857a46009c26318fa04c81d`.

The following GitHub Actions gates all completed with `SUCCESS` on that exact code SHA:

1. Merge conflict marker scan;
2. full CI, including Windows non-live pytest and Ruff correctness checks;
3. Context and long memory acceptance;
4. v0.16 process acceptance, including real Uvicorn/restart and Windows regression;
5. v0.18 Subagent offline acceptance on Windows;
6. v0.19 Durable background tasks acceptance;
7. v0.20 Plan Mode and Skills acceptance;
8. v0.21 LSP semantic tools acceptance, including a real local `pylsp` process;
9. full Desktop Playwright interaction suite, including i18n and Provider flows;
10. Windows Desktop package smoke with modular asset verification.

Automated repository acceptance status: **PASS**.

## Evidence boundaries

The validation layers must remain distinct:

- Fake/scripted-model Subagent tests are deterministic offline acceptance, not live-provider evidence.
- The v0.21 `pylsp` test is a real local language-server process test, not a fake protocol-only claim.
- Desktop Playwright is a real Chromium interaction test against local production assets, but it is not a manual native pywebview usability review.
- Windows package smoke proves the executable/asset package is built and structurally complete; it is not a human UI sign-off.

## Remaining manual/live acceptance

### Real Mistral Subagent acceptance — PENDING

The only release-level validation still intentionally pending is the live Mistral two-worker Subagent scenario.

Workflow:

- `.github/workflows/v018-mistral-live-acceptance.yml`
- trigger: `workflow_dispatch`
- required repository secret: `MISTRAL_API_KEY`

A green live workflow must capture evidence from the real Provider call. Offline Fake/ScriptedModel results must not be substituted for this evidence.

Do not commit API keys or copy credentials into repository artifacts.

## Merge recommendation

- Keep PR #50 Draft until the real Mistral workflow has been run and reviewed.
- Do not re-merge historical PRs #43/#44/#46/#47/#48.
- After live Mistral acceptance succeeds, review PR #50 once more and merge only the corrective PR.

Status: **AUTOMATED ACCEPTANCE COMPLETE / LIVE MISTRAL PENDING**.
