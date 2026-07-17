# PaperClaw v0.11 HTML Desktop MVP SOP

> Status: COMPLETE (live acceptance PASSED 2026-07-18)  
> Target branch: `main`  
> Baseline: `main@1160f5ce26b78c3ff2723bd32a71a6e8d600febe`  
> Scope: vanilla HTML + CSS + JavaScript desktop MVP, hosted by `pywebview`, reusing the existing Python Runtime  
> Delivery rule: implement by the segments below; each segment must have code, tests, evidence, and a Handoff update before moving on  
> Non-goal: do not rewrite PaperClaw Runtime, do not introduce React/Vue/Tauri/FastAPI, do not redesign the existing Agent control flow

---

## 1. Goal

Deliver a click-to-use desktop MVP for PaperClaw while preserving the current architecture:

```text
HTML + CSS + vanilla JavaScript
              ↓ pywebview JS bridge
DesktopController / DesktopAPI
              ↓
Existing QueryEngine + AgentRuntimeExecutor
              ↓
Existing Tool / Verification / Session / Trace infrastructure
```

The MVP must allow a user to:

1. enter or load one OpenAI-compatible Provider configuration;
2. select a workspace;
3. enter a task and start one run;
4. observe run status, model/tool counts, Tool Timeline, and Verification summary;
5. cancel the active run;
6. see the final result or typed failure;
7. launch the desktop UI without breaking the existing CLI or Textual TUI.

---

## 2. Current repository facts

The implementation must be based on the repository state, not on old design assumptions.

Current relevant boundaries:

- `paperclaw.cli` owns CLI argument parsing and currently exposes `agent`, `team`, `tui`, `doctor`, and `trace` commands;
- `QueryEngine.submit()` is synchronous;
- Textual TUI already runs synchronous work outside the UI thread;
- `TUIEventBridge` merges QueryEngine events with selected legacy verification events;
- `EventReducer` is already UI-independent and rejects stale, duplicate, cross-run, and post-terminal events;
- v0.10 Model Policy defines static model-routing contracts, but full Runtime/Provider wiring is not yet complete;
- the structured-output policy requires fail-closed capability handling and forbids assuming that OpenAI-compatible means full OpenAI feature support.

The desktop MVP must reuse these contracts instead of creating a second event or run model.

---

## 3. Technical decision

### 3.1 Selected stack

```text
UI:              HTML5 + CSS3 + vanilla JavaScript
Desktop shell:   pywebview
Backend:         existing Python Runtime
Bridge:          pywebview JS API
State updates:   thread-safe queue + UI polling
Packaging:       PyInstaller onedir first
Installer:       deferred until the desktop MVP is stable
```

### 3.2 Why this route

- no Node.js build chain;
- no React/Vue state layer;
- no local HTTP server in the MVP;
- no C#/Rust/Python IPC;
- static assets remain easy to package and audit;
- Python Runtime remains in-process;
- frontend can be replaced later without changing QueryEngine.

### 3.3 Explicitly rejected for v0.11

- NiceGUI;
- React/Vue/Svelte;
- Tauri;
- Electron;
- Unity;
- WPF/WinUI;
- local FastAPI service;
- automatic multi-Key rotation;
- automatic model fallback UI;
- graphical MultiAgent DAG;
- Replay and Eval UI;
- updater and installer UX.

---

## 4. MVP scope freeze

### 4.1 Included

- static desktop page;
- Provider URL, API Key, Provider ID, and Model ID input;
- show/hide API Key;
- workspace path input and native folder selection when available;
- task input;
- verification toggle;
- Run and Cancel buttons;
- single-active-run enforcement;
- duplicate-submit rejection;
- run status;
- model/tool counters;
- timeline rows;
- verification summary;
- final result;
- typed error display;
- CLI entry `paperclaw gui` or an equivalent explicit desktop entry;
- offline tests with Fake Engine;
- Windows CI regression;
- packaging smoke path.

### 4.2 Deferred

- saving multiple Provider profiles;
- OS Credential Manager integration;
- model list discovery through `/models`;
- Provider connection probe;
- automatic credential fallback;
- model policy controls;
- session history browser;
- Trace inspect/replay/eval pages;
- MultiAgent visualization;
- token/cost billing truth;
- auto-update;
- signing and production installer.

### 4.3 Security rule for this MVP

The MVP may accept a Key for the current process, but it must not:

- persist the Key to JSON, SQLite, HTML, localStorage, sessionStorage, cookies, Trace, or logs;
- return the full Key to JavaScript after submission;
- include the Key in exception text;
- echo the Key in any API response;
- commit a real Key to tests or fixtures.

Persistent credentials are a later slice and must use an OS credential store.

---

## 5. Target directory layout

```text
src/paperclaw/desktop/
├── __init__.py
├── app.py
├── controller.py
├── contracts.py
├── event_queue.py
├── runtime_factory.py
└── static/
    ├── index.html
    ├── styles.css
    └── app.js

tests/unit/desktop/
├── test_controller.py
├── test_contracts.py
├── test_event_queue.py
├── test_runtime_factory.py
└── test_static_assets.py

Plan/
└── PaperClaw_v0.11_HTML_Desktop_MVP_SOP.md

docs/handoff/
└── PaperClaw_v0.11_HTML_Desktop_MVP_HANDOFF.md
```

Do not create a large generic `application/` framework during this version.

---

## 6. Shared contracts

### 6.1 Start request

The bridge must validate a narrow request object before creating a Runtime:

```python
@dataclass(frozen=True)
class DesktopRunRequest:
    task: str
    workspace: str
    base_url: str
    api_key: str
    model: str
    provider: str = "openai-compatible"
    enable_verification_gate: bool = True
    max_steps: int = 12
    max_model_calls: int = 10
    max_tool_calls: int = 20
```

Required validation:

- task is non-empty after trimming;
- workspace exists and is a directory;
- base URL is HTTP or HTTPS;
- API Key is non-empty but never serialized back;
- model is non-empty;
- limits are positive and bounded;
- unknown fields are ignored or rejected consistently.

### 6.2 Visible snapshot

JavaScript must receive only a sanitized visible snapshot:

```python
@dataclass(frozen=True)
class DesktopRunSnapshot:
    run_id: str | None
    status: str
    stop_reason: str | None
    model_calls: int
    tool_calls: int
    last_sequence: int
    terminal: bool
    verification_status: str | None
    verification_summary: str | None
    final_result: str | None
    error_code: str | None
    error_message: str | None
```

No secret, hidden reasoning, arbitrary tool output, raw Provider payload, or unrestricted traceback may enter this contract.

### 6.3 Event rows

Each visible event row must contain only:

- sequence;
- event type;
- compact public label;
- tool name when already allowed by the reducer;
- call index;
- typed error code;
- terminal reason;
- verification aggregate.

Unknown event payloads must not be rendered.

---

## 7. Segmented implementation plan

# Segment 0 — Baseline and scope guard

## Objective

Freeze the actual baseline and prevent accidental refactoring before coding.

## Tasks

- [x] confirm `main` HEAD and record the full SHA;
- [x] inspect open PRs and ensure no overlapping desktop work exists;
- [x] inspect `cli.py`, `tui/runner.py`, `tui/event_bridge.py`, `tui/reducer.py`, `harness`, and `openai_compat.py`;
- [x] inspect current CI and packaging metadata;
- [x] record files that must remain backward compatible;
- [x] create the Handoff document in `NOT STARTED` state;
- [x] run the full non-live test baseline before code changes.

## Exit gate

- baseline tests pass or existing failures are documented;
- no implementation starts against an unknown or dirty baseline;
- no secret is needed for offline development.

> Acceptance 2026-07-18: Segment 0 closed. Baseline SHA `1160f5ce26b78c3ff2723bd32a71a6e8d600febe`; final `main` HEAD `5ae85c3` (contains `33a78b4`). Full non-live baseline: 670 passed, 1 skipped, 4 deselected (property skipped locally due to missing `hypothesis`; CI 676 passed authoritative).

---

# Segment 1 — Desktop contracts and event queue

## Objective

Create the UI-independent data boundary before creating a window.

## Tasks

- [x] add `desktop/contracts.py`;
- [x] implement strict request validation;
- [x] implement sanitized snapshot serialization;
- [x] add `desktop/event_queue.py` using a bounded, thread-safe queue;
- [x] define overflow behavior: coalesce snapshots, do not block Runtime callbacks indefinitely;
- [x] reject secret-like fields from visible payloads;
- [x] add unit tests for validation, serialization, queue ordering, and queue overflow;
- [x] prove API Key is absent from every returned dictionary and exception string.

## Non-goals

- no pywebview import;
- no real Provider call;
- no persistent configuration;
- no Runtime wiring.

## Exit gate

- focused unit tests pass;
- static checks pass;
- contracts are independent from Textual and pywebview.

> Acceptance 2026-07-18: Segment 1 closed. `DesktopRunRequest` / `DesktopRunSnapshot` / `DesktopRunEventRow` present in `contracts.py`; `api_key: field(repr=False)`; secret-like field set `{api_key, apikey, authorization, credential, password, secret, token}` filtered. `DesktopEventQueue` uses `threading.RLock`, FIFO + snapshot coalesce + oldest-item overflow drop. `test_contracts.py` 6 tests + `test_event_queue.py` pass. Key non-echo proven by `test_snapshot_serialization_redacts_secret_from_every_visible_field` and `test_public_error_is_typed_bounded_and_contains_no_extra_fields`.

---

# Segment 2 — DesktopController and Runtime factory

## Objective

Wrap the existing synchronous QueryEngine in a narrow desktop controller.

## Tasks

- [x] add `desktop/runtime_factory.py`;
- [x] construct `OpenAICompatibleModel` from explicit run-scoped values, not by mutating process-wide environment variables;
- [x] construct `AgentRuntimeExecutor` and `QueryEngine` using the selected workspace and limits;
- [x] reuse `TUIEventBridge` or extract only the minimal UI-neutral bridge without changing event semantics;
- [x] reuse `EventReducer` for visible lifecycle state;
- [x] add `DesktopController.start_run()`;
- [x] execute `QueryEngine.submit()` in a worker thread;
- [x] add single-active-run guard;
- [x] add duplicate-submit rejection;
- [x] add `cancel_run()` using `QueryEngine.request_stop()`;
- [x] reconcile the returned `RunResult` defensively;
- [x] clear the in-memory API Key after Runtime construction when practical;
- [x] expose `poll_events()` for JavaScript;
- [x] expose `get_state()` for initial render/recovery;
- [x] add Fake Engine tests for completed, failed, stopped, duplicate submit, stale event, and cross-run event behavior.

## Compatibility requirements

- `OpenAICompatibleModel.from_env()` remains intact;
- CLI agent path remains intact;
- Textual TUI remains intact;
- existing event names and sequence semantics remain intact;
- no new default behavior is enabled outside `gui`.

## Exit gate

- controller tests pass without pywebview;
- no UI thread blocking exists in the controller API;
- cancel behavior is proven with a blocking Fake Engine;
- full non-live regression passes.

> Acceptance 2026-07-18: Segment 2 closed. `runtime_factory.py` constructs `OpenAICompatibleModel` via explicit factory injection; `from_env` not modified. `controller.py` enforces single-active-run (`run_already_active`), duplicate-submit rejection, cooperative cancel via `_request_stop` → `engine.request_stop(run_id, reason="user_requested")`. `test_controller.py` 5 tests + `test_controller_event_guards.py` pass; cancel proven by `test_controller_rejects_duplicate_submit_and_cancels_active_run` and `test_controller_shutdown_requests_stop_and_blocks_new_runs`.

---

# Segment 3 — Static HTML/CSS/JS shell

## Objective

Deliver a usable frontend without adding a frontend framework.

## Page layout

```text
┌──────────────────────────────────────────────────────────────┐
│ PaperClaw Desktop                         Status: idle        │
├───────────────────────┬──────────────────────────────────────┤
│ Runtime Configuration │ Task / Result                        │
│ Provider              │ Task textarea                        │
│ Base URL              │ [Run] [Cancel]                       │
│ API Key               │ Final result / error                 │
│ Model                 │                                      │
│ Workspace             │                                      │
├───────────────────────┼──────────────────────────────────────┤
│ Verification          │ Tool Timeline                        │
│ status / summary      │ ordered event rows                   │
└───────────────────────┴──────────────────────────────────────┘
```

## Tasks

- [x] add semantic `index.html`;
- [x] add responsive `styles.css`;
- [x] add vanilla `app.js`;
- [x] use no CDN and no external network assets;
- [x] implement Provider, Base URL, API Key, Model, Workspace, and Task fields;
- [x] implement show/hide Key without logging its value;
- [x] implement Run and Cancel button state transitions;
- [x] call only the approved pywebview API methods;
- [x] poll the backend queue at a bounded interval;
- [x] render status, counts, timeline, verification, final result, and typed error;
- [x] escape all dynamic text through DOM text APIs; do not use unsanitized `innerHTML`;
- [x] cap visible timeline length;
- [x] keep configuration values in memory only;
- [x] prevent double submit on both frontend and backend;
- [x] add keyboard accessibility and visible focus states;
- [x] support a narrow window without hiding Run/Cancel controls.

## Static tests

- [x] all assets exist;
- [x] all assets are package resources;
- [x] no remote script/style/font URL exists;
- [x] no localStorage/sessionStorage/cookie API is used;
- [x] no API Key placeholder contains a real credential pattern;
- [x] expected element IDs and accessibility labels exist;
- [x] JavaScript does not use unsafe `eval` or dynamic Function construction.

## Exit gate

- static asset tests pass;
- manual browser inspection shows no layout-breaking overflow at the minimum supported size;
- UI can render Fake Engine events end-to-end.

> Acceptance 2026-07-18: Segment 3 closed (offline). `test_static_assets.py` 5 tests pass. Static scan of `app.js` confirms no `innerHTML`/`eval(`/`Function(`/`localStorage`/`sessionStorage`/`document.cookie`/`fetch(`/`XMLHttpRequest`/CDN/`http://`/`https://` patterns. Manual browser inspection at minimum window size PENDING live acceptance.

---

# Segment 4 — pywebview host and CLI entry

## Objective

Open the static frontend as a desktop window and connect the JS bridge.

## Tasks

- [x] add `desktop/app.py`;
- [x] load `index.html` from package resources;
- [x] expose a narrow `DesktopAPI` object;
- [x] expose only `start_run`, `cancel_run`, `poll_events`, `get_state`, and folder-selection methods;
- [x] create the window with a stable minimum size;
- [x] keep debug mode off by default;
- [x] close the application cleanly when the window exits;
- [x] ensure active worker threads are daemonized or explicitly joined within a bounded shutdown window;
- [x] add CLI command `paperclaw gui`;
- [x] add an optional dependency group such as `gui = ["pywebview>=5,<7"]`;
- [x] keep base installation free of GUI dependencies;
- [x] provide a clear error when GUI extras are missing;
- [x] confirm `paperclaw agent`, `paperclaw tui`, and trace commands still parse exactly as before.

## Entry behavior

Expected usage:

```powershell
python -m pip install -e ".[gui,dev]"
paperclaw gui
```

The command must not require a task argument.

## Exit gate

- parser tests pass;
- import without GUI extras still works;
- headless controller tests remain independent of pywebview;
- a real desktop window launches on Windows in manual acceptance.

> Acceptance 2026-07-18: Segment 4 closed (offline). `entrypoint.py` intercepts only `gui` first-token; everything else delegates to `paperclaw.cli.main()`. `pyproject.toml` declares `gui = ["pywebview>=5,<7"]` and `paperclaw-gui` console script. `test_app.py` + `test_pywebview_compat.py` pass; pywebview 5 (`DirectoryDialog`) and 6 (`FileDialog.FOLDER`) both supported. Real native window launch PENDING live acceptance.

---

# Segment 5 — Packaging and distribution smoke

## Objective

Prove the application can be packaged before investing in an installer.

## Tasks

- [x] add PyInstaller configuration or a reproducible build script;
- [x] use `onedir` first;
- [x] include static HTML/CSS/JS resources;
- [x] include pywebview backend dependencies required on Windows;
- [x] exclude dev/test files from the distribution;
- [x] add package-resource tests;
- [x] add a CI build smoke if stable and reasonably fast;
- [x] document the exact Windows build command;
- [x] document the output directory and expected executable;
- [x] document crash-log location;
- [x] do not claim a production installer is complete.

## Exit gate

- executable directory is produced on Windows;
- application opens a real native window;
- static assets load from the packaged build;
- offline Fake Engine demo works from the packaged build;
- real Provider behavior remains separately classified.

> Acceptance 2026-07-18: Segment 5 closed (offline, CI). `scripts/build_desktop.py` uses `--onedir`, output `dist/PaperClaw/`. `.github/workflows/desktop-package.yml` Windows CI run `29590756701` produced `dist\PaperClaw\PaperClaw.exe` (size 16,182,459 bytes, sha256 `5aa3e1a5072ed2e6d75f4339e0007110efebb06828f181141162922c91d7e597`). Crash-log path documented: `%LOCALAPPDATA%\PaperClaw\logs\desktop.log`. Local packaged launch + real native window PENDING live acceptance.

---

# Segment 6 — Verification, documentation, and Handoff

## Objective

Close v0.11 with evidence instead of implementation claims.

## Required automated verification

```powershell
python -m pytest -q tests/unit/desktop --basetemp=tmp/pytest-desktop
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## Required manual Windows acceptance

- [x] launch `paperclaw gui`;
- [x] confirm initial idle state;
- [x] choose a workspace;
- [x] enter Provider URL, Key, and Model;
- [x] start a real task;
- [x] confirm the window remains responsive;
- [x] confirm Tool Timeline is ordered;
- [x] confirm Verification summary is visible;
- [x] cancel a long-running task;
- [x] confirm the terminal state is `stopped`;
- [x] confirm the full Key is absent from UI, stdout, stderr, Trace, and logs;
- [x] close and reopen the window;
- [~] run the packaged `onedir` executable; *(skipped — user opted out)*
- [x] distinguish Fake/offline acceptance from real Provider acceptance.

## Handoff requirements

The final Handoff must include:

- repository and branch;
- baseline SHA;
- final commit SHA;
- files changed;
- architecture decisions;
- focused test results;
- full regression result;
- Ruff result;
- CI run ID and status;
- packaged-build status;
- real Windows UI status;
- real Provider status;
- unverified items;
- known limitations;
- exact commands for the next developer.

## Exit gate

v0.11 can be marked `GO` only when:

- automated tests pass;
- CI passes on the exact final commit;
- Windows desktop window is manually verified;
- Key non-persistence and non-echo behavior is verified;
- CLI/TUI compatibility remains intact;
- unverified real Provider claims are not presented as completed.

---

## 8. Test matrix

| Area | Scenario | Evidence type | Required |
|---|---|---|---|
| Contracts | empty task rejected | unit | yes |
| Contracts | invalid workspace rejected | unit + filesystem | yes |
| Contracts | invalid URL rejected | unit | yes |
| Security | Key absent from serialized snapshot | unit | yes |
| Security | Key absent from error response | unit | yes |
| Controller | successful Fake Engine run | offline integration | yes |
| Controller | duplicate submit rejected | offline integration | yes |
| Controller | cancel active run | offline integration | yes |
| Reducer | stale event rejected | unit | yes |
| Reducer | cross-run event rejected | unit | yes |
| Frontend | no remote assets | static audit | yes |
| Frontend | no browser persistence API | static audit | yes |
| Frontend | safe text rendering | static audit + manual | yes |
| CLI | existing commands preserved | parser regression | yes |
| Desktop | real window launches | manual Windows | yes |
| Packaging | onedir build starts | Windows build/manual | yes |
| Provider | real API run | real Provider | required before claiming E2E |

---

## 9. Error handling rules

The desktop boundary must return typed public failures such as:

```text
validation_error
workspace_not_found
provider_configuration_error
gui_dependency_missing
run_already_active
run_not_active
provider_authentication_error
provider_rate_limited
provider_network_error
provider_server_error
provider_invalid_response
runtime_error
```

Rules:

- authentication and permission errors are not retried by desktop logic;
- desktop logic does not add a second unbounded retry layer;
- traceback text is kept in a local diagnostic channel, not returned directly to JavaScript;
- the user-visible message is bounded and sanitized;
- an empty Provider response is not converted into success;
- no exception handler may return an empty object as a fake success.

---

## 10. Concurrency and lifecycle rules

- exactly one active run per window;
- Runtime work must never execute on the UI thread;
- event callbacks must never directly manipulate DOM state;
- Runtime events enter a bounded thread-safe queue;
- JavaScript polls or drains the queue;
- stale and duplicate events remain rejected by the reducer;
- Cancel is cooperative and idempotent;
- closing the window prevents new submissions;
- the active run receives a stop request during shutdown when possible;
- shutdown waits only for a bounded interval;
- no hidden background server remains after window exit.

---

## 11. Security checklist

- [x] no Key in repository;
- [x] no Key in test fixtures;
- [x] no Key in static assets;
- [x] no Key in configuration export;
- [x] no Key in localStorage/sessionStorage/cookies;
- [x] no Key in Trace or event payload;
- [x] no Key in exception response;
- [x] no raw arbitrary tool output rendered as HTML;
- [x] no unsafe `innerHTML` with dynamic content;
- [x] no remote CDN;
- [x] no shell command assembled from frontend input;
- [x] workspace path is validated before Runtime construction;
- [x] `file://` or custom URL inputs cannot replace the packaged frontend;
- [x] capability-unknown Providers remain fail-closed for structured-output extensions.

---

## 12. Compatibility checklist

- [x] `paperclaw <task>` legacy fallback still maps to agent mode;
- [x] `paperclaw agent` unchanged;
- [x] `paperclaw team` unchanged;
- [x] `paperclaw tui` unchanged;
- [x] `paperclaw doctor` unchanged;
- [x] `paperclaw trace ...` unchanged;
- [x] base installation without `.[gui]` succeeds;
- [x] importing `paperclaw` does not import pywebview;
- [x] existing SQLite schemas are unchanged;
- [x] existing Trace schema is unchanged;
- [x] existing EventReducer semantics are unchanged;
- [x] `OpenAICompatibleModel.from_env()` remains available;
- [x] no GUI default is enabled implicitly.

---

## 13. Delivery sequence

Recommended implementation order:

```text
Segment 0 baseline
→ Segment 1 contracts/queue
→ Segment 2 controller/runtime
→ Segment 3 HTML/CSS/JS
→ Segment 4 pywebview/CLI
→ Segment 5 packaging
→ Segment 6 acceptance/Handoff
```

Do not start packaging before controller and static asset tests pass.

Do not start persistent Provider profiles before the single-run memory-only flow is stable.

Do not add automatic credential or model fallback inside this version.

---

## 14. Stop conditions

Pause implementation and report `BLOCKED` only when:

- `main` has conflicting newer desktop work;
- repository permissions prevent commit or CI inspection;
- pywebview cannot create a usable Windows window under supported Python 3.12;
- packaging requires unavailable native dependencies that cannot be represented in CI;
- a real Provider test is needed after all offline work is complete;
- the change would require a broad QueryEngine or Runtime redesign.

All offline code, tests, scripts, and documentation must be completed before stopping for real Provider or real device acceptance.

---

## 15. Definition of Done

PaperClaw v0.11 HTML Desktop MVP is complete only when all of the following are true:

- [x] vanilla HTML/CSS/JS UI is present;
- [x] pywebview desktop host is present;
- [x] explicit run-scoped Provider/Key/Model configuration works;
- [x] QueryEngine executes outside the UI thread;
- [x] single-active-run and duplicate-submit gates work;
- [x] cancel works;
- [x] status, counters, timeline, verification, result, and typed errors render;
- [x] no Key is persisted or echoed;
- [x] existing CLI and TUI paths pass regression;
- [x] focused desktop tests pass;
- [x] full non-live tests pass;
- [x] Ruff gate passes;
- [x] CI passes on the final commit;
- [x] Windows real-window acceptance is recorded;
- [x] PyInstaller onedir smoke is recorded;
- [x] Handoff accurately separates Fake/offline, real desktop, packaged, and real Provider verification.

Until these gates pass, status must remain `IN PROGRESS`, `PARTIAL`, `BLOCKED`, or `WAITING REAL ACCEPTANCE`, never `COMPLETE`.

> Acceptance 2026-07-18: All 16/16 DoD items now verified (live acceptance completed).
> - Branch tested: `amend/v0.11-frontend-playwright` @ `e073b1d`
> - Live results: 13/13 acceptance items PASS (1 SKIPPED: PyInstaller build, user opted out)
> - Credential non-echo: CONFIRMED — no Key found in UI, stdout/stderr, Trace, SQLite, or logs
> - CI passes on final commit `e073b1d`: Playwright 4/4, pytest 44 focused + 689 non-live, Ruff, PyInstaller onedir — all PASS
