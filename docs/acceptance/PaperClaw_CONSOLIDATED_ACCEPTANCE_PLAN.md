# PaperClaw Consolidated Acceptance Plan

## 1. Purpose

This plan accepts the consolidated change set represented by PR #42. It covers the desktop application, manual Provider configuration, durable Service API, restart recovery, tool authorization, research evaluation, automatic context compaction, project instructions, long memory, and user-profile memory.

The release candidate is accepted only against one immutable Git commit. Record the exact PR head SHA before starting and reject evidence produced from a different SHA.

## 2. Acceptance roles

| Role | Responsibility |
|---|---|
| Release owner | Freezes the candidate SHA and decides release disposition |
| Technical reviewer | Reviews architecture, security boundaries, persistence, and failure handling |
| Test operator | Executes automated and manual scenarios and records evidence |
| Product acceptor | Confirms the desktop and CLI workflows meet expected behavior |

One person may hold multiple roles, but the release owner must explicitly sign the final checklist.

## 3. Test environments

### Required

- Windows 11, Python 3.12
- Ubuntu GitHub Actions runner, Python 3.12
- Chromium installed through Playwright
- Writable temporary workspace
- Loopback networking available for the mock OpenAI-compatible Provider and Uvicorn Service API

### Optional external-provider smoke test

Use a dedicated low-privilege test credential. Never use a production credential and never commit the credential or copy it into test artifacts.

## 4. Entry criteria

All conditions must be true before manual acceptance begins:

- PR #42 targets `main` and is mergeable;
- only one consolidated feature PR remains open for this release chain;
- exact-head automated workflows are complete;
- no Critical or High review finding is open;
- generated artifacts identify the same head SHA;
- the working tree used for manual testing is clean;
- no real Provider credential exists in repository files, logs, SQLite fixtures, screenshots, or uploaded artifacts.

## 5. Automated acceptance gates

### Gate A — Windows non-live regression

Run the complete non-live pytest suite on Windows.

Pass criteria:

- zero failed tests;
- process-acceptance tests are either explicitly excluded or executed in their dedicated Linux job;
- Playwright tests are either executed in the browser job or explicitly skipped by their documented setup gate;
- pytest report artifact is uploaded.

### Gate B — Real-process Service API recovery

Start the mock Provider and `paperclaw-api` as independent OS processes.

Required assertions:

1. submit a run through public HTTP;
2. poll the same run to a terminal state;
3. replay persisted SSE events;
4. resume SSE with `Last-Event-ID` without duplicate older events;
5. repeat the same Idempotency-Key and receive the original run;
6. kill the Service process while the Provider call is in flight;
7. restart against the same SQLite database after lease expiry;
8. observe reconciliation of the original durable run ID;
9. observe exactly one durable finalization event;
10. verify all child processes are stopped during teardown.

Pass criteria: all process tests pass and the artifact contains logs, Provider state, pytest results, and SQLite evidence.

### Gate C — Context and long-memory focused acceptance

Run the dedicated Context/Memory test set.

Required coverage:

- compaction threshold behavior;
- preservation of full audit history;
- bounded recent Tool output with SHA-256 reference;
- frozen session-start memory snapshot;
- confidence filtering;
- project instruction imports and workspace escape rejection;
- capacity and privacy failures;
- cross-process memory writes;
- unauthenticated Service API memory isolation;
- CLI, TUI, Desktop, and Service runtime composition.

Pass criteria: zero failures and JUnit plus console-log artifacts are uploaded.

### Gate D — Desktop browser interaction

Run Playwright against Chromium.

Required assertions:

- application shell loads without console errors;
- Provider configuration panel opens and closes;
- manual Base URL, API Key, model, and Provider fields can be edited;
- failed model discovery does not erase the user's manual model value;
- reconnect failure preserves the last explicit configuration;
- protected browser mode does not expose the API Key in DOM text, console logs, query strings, or screenshots;
- run submission and visible event updates work with the mock Provider.

Pass criteria: all browser tests pass and the Playwright artifact is uploaded.

### Gate E — Packaging

Build the Windows PyInstaller `onedir` package.

Pass criteria:

- executable starts on a clean Windows test account;
- packaged HTML, CSS, and JavaScript assets are present;
- the application can open the desktop UI;
- no source checkout is required at runtime;
- package artifact digest is recorded.

### Gate F — Static correctness

Run the configured Ruff correctness gate.

Pass criteria: no E9, F63, F7, or F82 violation under the repository's documented exclusions.

## 6. Manual functional acceptance

### Scenario 1 — Desktop first-run Provider configuration

1. Start the packaged Desktop application without Provider environment variables.
2. Open Provider settings.
3. Enter a loopback mock Provider URL, test API Key, Provider name, and explicit model.
4. Save and reconnect.
5. Submit a simple workspace inspection task.

Expected:

- the explicit model remains selected;
- the request reaches the mock Provider;
- the UI shows accepted, running, Tool activity, and terminal state;
- the API Key is not rendered in visible logs or persisted public events.

### Scenario 2 — Workspace environment isolation

1. Create workspace A with a test `.env` Provider configuration.
2. Start a run in workspace A.
3. Create workspace B without those values.
4. Start a run in workspace B.

Expected: workspace B does not inherit workspace A credentials through process-global environment mutation.

### Scenario 3 — Project instructions

1. Add `PAPERCLAW.md` with one observable instruction.
2. Import a second workspace file with `@docs/rules.md`.
3. Put another `@docs/ignored.md` reference inside a fenced code block.
4. Attempt `@../outside.md`.

Expected:

- the root instruction and valid workspace import enter foundational Context;
- the fenced reference is ignored;
- the escaping path is rejected;
- truncation is explicitly marked when configured limits are exceeded.

### Scenario 4 — Context compaction

1. Run a deterministic task that produces enough Tool output to cross the compaction threshold.
2. Inspect emitted events and Provider prompts in a test adapter.

Expected:

- `context.compaction.completed` is emitted;
- old entries are summarized;
- recent entries remain available in bounded form;
- large outputs include truncation state and SHA-256 reference;
- the full structured History remains available for replay and audit.

### Scenario 5 — User profile and long memory

1. Add one high-confidence `user` preference.
2. Add one low-confidence `user` preference.
3. Add one project convention to `memory`.
4. Start a new runtime.
5. Replace the high-confidence entry using a unique substring.
6. Remove it and start another runtime.

Expected:

- high-confidence data enters the next runtime snapshot;
- low-confidence data remains on disk but is not injected below the configured threshold;
- current-session foundational Context does not mutate after a write;
- replace and remove affect exactly one entry;
- file capacity overflow returns an explicit error and does not silently evict data.

### Scenario 6 — Memory privacy and concurrency

1. Attempt to store an API-key-shaped value and a private-key header.
2. Attempt to store the reserved entry delimiter.
3. Perform simultaneous writes from two independent processes.

Expected:

- secret-shaped and reserved-format data is rejected;
- both legitimate concurrent writes survive;
- no stale lock remains after normal completion.

### Scenario 7 — Service API durability

1. Start the Service API with a fresh SQLite database.
2. Submit a run with an Idempotency-Key.
3. Repeat the request.
4. Stream events, disconnect, and resume.
5. Cancel a second active run.
6. Kill and restart the service during a third run.

Expected:

- idempotent replay returns the original run;
- SSE sequence order is stable;
- cancellation reason, state, and event are atomically persisted;
- restart reconciliation does not create a second logical run;
- each run has no more than one terminal finalization event.

### Scenario 8 — Service personal-memory boundary

1. Start the unauthenticated Service API with default settings.
2. Inspect the available Tool registry and Context sources.
3. Repeat in a trusted single-user test deployment with `PAPERCLAW_SERVICE_PERSONAL_MEMORY_ENABLED=true`.

Expected:

- default Service API neither injects personal memory nor exposes the memory-write Tool;
- explicit trusted deployment opt-in enables the feature;
- invalid boolean configuration fails during startup rather than silently choosing a value.

### Scenario 9 — Tool authorization

Attempt:

- a permitted workspace-local file operation;
- a path outside the workspace;
- a credential-bearing URL;
- an ambiguous or disallowed network target;
- a permitted loopback mock Provider target.

Expected: allowed operations succeed and denied operations return stable policy errors without performing side effects.

### Scenario 10 — Research evaluation

Run the canonical evaluation generator and compare the documented baseline and retrieval/MCP/verification variants.

Expected:

- the canonical report is reproducible;
- metrics are calculated from the stored fixtures;
- the report identifies configuration and dataset provenance;
- no result is described as external-production evidence.

## 7. Non-functional acceptance

### Security

- no secret appears in public events, logs, screenshots, exception payloads, or committed fixtures;
- unauthenticated HTTP callers cannot share personal memory by default;
- workspace boundaries are enforced for file and imported instruction paths;
- network policy rejects credential-bearing and ambiguous targets.

### Reliability

- terminal state, metadata, lease release, transition, and final event are committed atomically;
- cancellation persistence is atomic;
- restart reconciliation preserves the durable run ID;
- child processes and lock files are cleaned up after success and failure.

### Performance

For the local acceptance environment:

- idle Service API health response completes within 1 second;
- a mock-Provider run begins execution within 2 seconds when capacity is available;
- Context compaction reduces rendered runtime-history tokens below the configured trigger;
- Desktop remains interactive while a run is active.

These are acceptance thresholds for the test environment, not production SLOs.

## 8. Evidence package

Retain for at least 30 days:

- exact Git SHA;
- GitHub Actions run IDs;
- JUnit or report-log artifacts;
- Playwright artifact;
- PyInstaller artifact and digest;
- process acceptance logs and SQLite databases;
- manual checklist with operator, timestamp, OS, and result;
- redacted screenshots for Desktop scenarios;
- final Code Review disposition.

Do not retain Provider credentials or unredacted user-profile content in the evidence package.

## 9. Release decision

### Accept

All automated gates pass at the exact candidate SHA, all mandatory manual scenarios pass, and no open Critical or High issue remains.

### Conditional accept

Only documentation, cosmetic UI, or explicitly recorded Medium/Low issues remain. Each issue must have an owner and follow-up target.

### Reject

Reject the candidate if any of the following occurs:

- data loss or duplicate terminal finalization;
- cross-workspace credential leakage;
- cross-client personal-memory leakage under default Service settings;
- workspace path escape;
- secret exposure in public evidence;
- failed restart reconciliation;
- mismatch between evidence SHA and candidate SHA;
- any Critical or High review finding remains open.

## 10. Final sign-off checklist

- [x] Candidate SHA recorded: `58e7900dd80c1ad5645ab683c3cdeccf4388bea1`
- [x] Consolidated PR targets `main`: PR #42 mergeable
- [x] Superseded PRs closed: #40, #41 closed
- [x] Windows regression passed: 765 passed, 0 failed
- [x] Real-process recovery passed: 2 passed, 0 failed
- [x] Context/Memory focused tests passed: 92 passed, 0 failed
- [x] Desktop Playwright passed: 5 passed, 0 failed
- [x] Windows package passed: PyInstaller onedir OK
- [x] Ruff gate passed: E9/F63/F7/F82 clean
- [x] Mandatory manual scenarios passed: 10/10 scenarios
- [x] Evidence package archived: `artifacts/v0_17_acceptance/`
- [x] No Critical or High finding open: 0 Critical, 0 High
- [ ] Release owner approved: **PENDING**
