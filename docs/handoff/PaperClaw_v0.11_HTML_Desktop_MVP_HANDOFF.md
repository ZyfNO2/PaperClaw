# PaperClaw v0.11 HTML Desktop MVP Handoff

## 1. Current status

**Status: `WAITING REAL ACCEPTANCE`**

The v0.11 implementation, focused offline tests, full non-live regression, Ruff gate, and Windows PyInstaller `onedir` build smoke are complete. The release must **not** be marked `COMPLETE` or `GO` until a human verifies the native Windows window, the packaged executable, a real Provider run, cooperative cancellation, and credential non-echo behavior on a real machine.

This Handoff intentionally distinguishes:

- **verified:** repository implementation, offline/Fake Engine behavior, static security checks, Windows CI regression, and `onedir` artifact production;
- **not verified:** real native-window usability, real Provider behavior, packaged executable launch, and real-run credential inspection.

## 2. Repository and delivery references

- Repository: `ZyfNO2/PaperClaw`
- Baseline branch: `main`
- Baseline SHA: `d5194ef76c5f0ae936a2664d8cd7d47635242b45`
- Development branch: `feat/v0.11-html-desktop-mvp`
- Draft PR: `#33` — `feat(v0.11): HTML desktop MVP`
- Final implementation SHA: `d3ab7d59a7378d428ad4368a3c462f9cd4489af6`
- Handoff/CI metadata commits after the implementation SHA do not change desktop runtime behavior.
- Merge state: **not merged**; PR remains Draft.

An older Draft PR `#32` contains separate Provider configuration foundation work based on an older `main`. It was not modified or merged into this implementation branch.

## 3. Implemented scope

### Desktop contracts and security boundary

- Added strict `DesktopRunRequest` validation for task, workspace, HTTP(S) Provider URL, Key, model, Provider ID, verification toggle, and bounded run limits.
- API Key is `repr=False`, never serialized into public snapshots or events, and is redacted from visible result/error fields.
- Public event rows use explicit allowlists; arbitrary Provider payloads, reasoning, and tool output are not rendered.
- Unknown event names may remain visible, but unknown payload fields are dropped.
- Added typed bounded public failures rather than raw tracebacks.

### Runtime and lifecycle

- Reused existing `QueryEngine`, `AgentRuntimeExecutor`, `TUIEventBridge`, and `EventReducer`.
- Builds `OpenAICompatibleModel` from explicit run-scoped values without mutating process-wide environment variables.
- Runs synchronous `QueryEngine.submit()` in a daemon worker thread, not the UI thread.
- Enforces one active run per window and rejects duplicate submissions in both JavaScript and Python.
- Implements cooperative, idempotent cancellation through `QueryEngine.request_stop()`.
- Uses a bounded thread-safe event queue with FIFO events, coalesced snapshots, and oldest-item overflow dropping.
- Reconciles the returned `RunResult` defensively.
- Performs bounded shutdown and prevents submissions after window close begins.

### HTML desktop client

- Added semantic HTML, responsive CSS, and vanilla JavaScript only.
- Added Provider ID, Base URL, API Key show/hide, Model ID, workspace path/folder picker, task, verification toggle, Run, and Cancel controls.
- Renders status, model/tool counters, ordered timeline, verification summary, final result, and typed errors.
- Uses DOM text APIs for dynamic output and caps the timeline length.
- Uses no CDN, remote asset, browser persistence API, unsafe `innerHTML`, `eval`, or dynamic `Function`.
- Clears the Key field and the submitted JavaScript payload after an accepted run start.

### pywebview host and compatibility

- Added delayed pywebview import so base installation and existing CLI/TUI paths remain free of GUI dependencies.
- Exposes only `start_run`, `cancel_run`, `poll_events`, `get_state`, and folder-selection operations to JavaScript.
- Supports the pywebview 5 legacy folder-dialog constant and pywebview 6 `FileDialog.FOLDER`.
- Keeps debug mode disabled by default and requests private browser mode.
- Added explicit `paperclaw gui`, `paperclaw-gui`, and `python -m paperclaw.desktop` launch paths.
- All non-GUI arguments continue to delegate to the existing `paperclaw.cli.main()` path.

### Packaging and diagnostics

- Added optional `gui` and `build` dependency groups.
- Added package-data declarations for HTML/CSS/JavaScript assets.
- Added a reproducible Windows PyInstaller `onedir` build script.
- Added Windows CI smoke verification for `PaperClaw.exe` and packaged static assets.
- Added a local, bounded, sanitized desktop host diagnostic log.
- Windows diagnostic log: `%LOCALAPPDATA%\PaperClaw\logs\desktop.log`
- Non-Windows diagnostic log: `$XDG_STATE_HOME/paperclaw/desktop.log` or `~/.local/state/paperclaw/desktop.log`

## 4. Main files added or changed

### Runtime and UI

- `src/paperclaw/entrypoint.py`
- `src/paperclaw/desktop/__init__.py`
- `src/paperclaw/desktop/__main__.py`
- `src/paperclaw/desktop/app.py`
- `src/paperclaw/desktop/contracts.py`
- `src/paperclaw/desktop/controller.py`
- `src/paperclaw/desktop/diagnostics.py`
- `src/paperclaw/desktop/event_queue.py`
- `src/paperclaw/desktop/runtime_factory.py`
- `src/paperclaw/desktop/static/index.html`
- `src/paperclaw/desktop/static/styles.css`
- `src/paperclaw/desktop/static/app.js`

### Packaging and CI

- `pyproject.toml`
- `scripts/build_desktop.py`
- `scripts/paperclaw_desktop_entry.py`
- `.github/workflows/desktop-package.yml`

### Focused tests

- `tests/unit/desktop/test_app.py`
- `tests/unit/desktop/test_contracts.py`
- `tests/unit/desktop/test_controller.py`
- `tests/unit/desktop/test_controller_event_guards.py`
- `tests/unit/desktop/test_diagnostics.py`
- `tests/unit/desktop/test_event_queue.py`
- `tests/unit/desktop/test_pywebview_compat.py`
- `tests/unit/desktop/test_runtime_factory.py`
- `tests/unit/desktop/test_static_assets.py`

## 5. Architecture decisions

1. **Wrapper entrypoint instead of modifying the legacy parser.** `paperclaw.entrypoint` intercepts only the exact `gui` command and delegates every other argument list unchanged to `paperclaw.cli.main()`. This minimizes parser and legacy positional-task regression risk.
2. **Existing event semantics are authoritative.** The desktop controller does not define a second lifecycle state machine. `TUIEventBridge` supplies ordered events and `EventReducer` rejects stale, duplicate, cross-run, and post-terminal events.
3. **No local HTTP server.** Python and JavaScript communicate only through the pywebview JS API and a bounded in-process queue.
4. **Run-scoped credentials only.** No JSON profile, SQLite field, environment mutation, browser storage, OS credential store, automatic Key rotation, or automatic model fallback was introduced.
5. **Public-data projection is fail-closed.** Event and snapshot fields are explicitly selected and bounded before crossing into JavaScript.
6. **`onedir` before installer.** The current artifact is a build smoke and distribution directory, not a signed installer or production release.

## 6. Automated verification

All results below are from exact implementation commit `d3ab7d59a7378d428ad4368a3c462f9cd4489af6`.

### Focused desktop tests

Command represented by CI:

```powershell
python -m pytest -q tests/unit/desktop `
  --basetemp=tmp/pytest-desktop `
  --report-log=tmp/desktop_pytest_reportlog.jsonl
```

Result:

- `38 passed`
- Workflow run: `29590756701`
- Report artifact: `desktop-pytest-results-29590756701`
- Artifact ID: `8410955720`
- Digest: `sha256:1da53f30e9f1e0e2badb2a14b06c74734bd9078ca990c9ff702626e43f21b915`

These tests are offline unit/control-flow/static tests. Fake engines and injected factories are used where a Provider would otherwise be required. They are **not** real Provider E2E evidence.

### Full non-live regression

Command represented by CI:

```powershell
python -m pytest -q -m "not real_llm" `
  --basetemp=tmp/pytest `
  --report-log=tmp/pytest_reportlog.jsonl
```

Result:

- `676 passed`
- Windows CI run: `29590756661`
- Report artifact: `pytest-results-29590756661`
- Artifact ID: `8411049213`
- Digest: `sha256:8076c8681eaec882c24a4e9728361e3742de34cb99dcbd6b750cbac77e669efd`

### Ruff

Command represented by CI:

```powershell
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

Result:

- `success`
- CI run: `29590756661`

### Windows PyInstaller `onedir` smoke

Command represented by CI:

```powershell
python scripts/build_desktop.py
```

Result:

- Build completed successfully on `windows-latest` with Python 3.12.
- `dist\PaperClaw\PaperClaw.exe` was present.
- Packaged `index.html`, `styles.css`, and `app.js` were present.
- Workflow run: `29590756701`
- Artifact: `PaperClaw-Windows-onedir-29590756701`
- Artifact ID: `8410966647`
- Size: `16,182,459` bytes
- Digest: `sha256:5aa3e1a5072ed2e6d75f4339e0007110efebb06828f181141162922c91d7e597`
- Artifact expiry: `2026-07-24T15:07:53Z`

This proves artifact production and static resource inclusion. It does **not** prove that the executable opens a usable native window.

## 7. Compatibility status

### Verified by code and automated regression

- Existing CLI argument lists are delegated unchanged unless the first token is exactly `gui`.
- Existing TUI modules and entry behavior were not modified.
- `OpenAICompatibleModel.from_env()` remains available and unchanged.
- Existing `QueryEngine`, Runtime, Trace, and SQLite schema files were not modified.
- Base installation does not require or import pywebview.
- No desktop behavior is enabled implicitly.

### Still requires manual confirmation

- `paperclaw agent`, `paperclaw team`, `paperclaw tui`, `paperclaw doctor`, and `paperclaw trace ...` should be sampled from the installed branch on the target Windows machine.
- Actual pywebview backend selection and WebView2 behavior must be observed on the target machine.

## 8. Not verified / blocked on real acceptance

The following claims remain `PENDING`:

1. A real Windows native window launches through `paperclaw gui`.
2. The native folder picker works on the target Windows installation.
3. The UI remains responsive during a real Provider request.
4. A real Provider accepts the supplied Base URL, Key, Provider ID, and Model ID.
5. Real authentication, rate-limit, network, server, and invalid-response errors map correctly end-to-end.
6. Cancellation stops a genuinely long-running Provider/tool run and terminates as `stopped`.
7. The full Key is absent from UI, JavaScript responses, stdout, stderr, Trace, SQLite, and diagnostic logs during a real run.
8. The downloaded/freshly built `dist\PaperClaw\PaperClaw.exe` opens and loads all packaged assets.
9. The responsive layout is visually acceptable at the minimum window size.
10. Close-during-run behavior leaves no hidden process on the target machine.

No live key or external paid Provider was used in automated development.

## 9. Required Windows acceptance procedure

### Editable installation

```powershell
git checkout feat/v0.11-html-desktop-mvp
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[gui,dev]"
paperclaw gui
```

Use a disposable or low-privilege Provider Key where possible. In the window:

1. Confirm the initial status is `idle`.
2. Use **Browse** to select an existing workspace directory.
3. Enter Provider ID, Base URL, Key, and Model ID.
4. Enter a harmless task that produces an observable file or report.
5. Start the run and confirm the window remains responsive.
6. Confirm status, model/tool counters, timeline order, verification status/summary, and final result.
7. Start a sufficiently long task and press **Cancel**.
8. Confirm the terminal state becomes `stopped` with a user-requested reason.
9. Attempt a second submission while a run is active and confirm it is rejected.
10. Repeat once with an invalid Key and confirm a typed authentication error appears without raw Provider payload or traceback.
11. Close the window during a run and confirm no PaperClaw process remains after the bounded shutdown period.

### Package build and launch

```powershell
python -m pip install -e ".[build]"
python scripts/build_desktop.py
.\dist\PaperClaw\PaperClaw.exe
```

Repeat the idle, workspace picker, one real task, cancellation, close/reopen, and invalid-Key checks in the packaged executable.

### Credential inspection

After the real run, search the chosen test Key in:

- visible UI and copied result text;
- PowerShell stdout/stderr capture;
- workspace Trace and SQLite files, if created by the task path;
- `%LOCALAPPDATA%\PaperClaw\logs\desktop.log`;
- any application-specific logs produced during acceptance.

**Pass:** the full Key appears nowhere outside the Provider request process memory/input field before submission.

**Fail:** the full Key appears in any API response, event, snapshot, traceback, Trace, database, browser storage, stdout/stderr, or local diagnostic log.

### Evidence to return

Return:

- screenshot of initial idle window;
- screenshot of a completed run with timeline and verification visible;
- screenshot of a cancelled run showing `stopped`;
- screenshot of packaged executable running;
- PowerShell output for installation/build/launch;
- `%LOCALAPPDATA%\PaperClaw\logs\desktop.log` only if an error occurred, after checking it contains no credential;
- Provider/model identifiers used, but **never the Key**;
- any reproducible failure steps.

## 10. Known limitations

- One active run per desktop window.
- No persisted Provider profiles or credentials.
- No OS Credential Manager integration.
- No Provider connection probe or `/models` discovery.
- No automatic Key rotation or model fallback.
- No session-history, Trace replay/eval, or MultiAgent graph UI.
- No token/cost billing truth in the desktop client.
- No installer, signing, auto-update, or production distribution policy.
- Queue overflow drops the oldest pending item and increments an internal dropped counter; it does not persist an event replay log.
- Diagnostic logging covers unexpected desktop host failures; ordinary typed Runtime/Provider failures remain in sanitized UI state rather than full local tracebacks.

## 11. Next developer steps

1. Check out `feat/v0.11-html-desktop-mvp` and confirm the Draft PR head.
2. Run the focused tests, full non-live regression, and Ruff commands shown above.
3. Perform the full Windows acceptance procedure with a disposable Provider credential.
4. Launch and test the PyInstaller `onedir` executable.
5. Record screenshots, logs, Provider/model identifiers, and pass/fail results without recording the Key.
6. Update this Handoff with real-window, packaged-launch, real-Provider, cancellation, and credential-inspection evidence.
7. Only after all required manual gates pass, change status from `WAITING REAL ACCEPTANCE` to `GO`.
8. Keep PR `#33` Draft until the acceptance evidence has been reviewed. Do not merge automatically.
