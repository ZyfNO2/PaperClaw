# PaperClaw v0.11 Frontend + Playwright Amendment

## Status

**Status: `IMPLEMENTED / CI PENDING / NATIVE WINDOWS ACCEPTANCE PENDING`**

This amendment replaces the original v0.11 visual shell with the user-provided Neo-Brutalist console design and changes the default desktop provider path back to environment-backed configuration.

## Baseline

- Repository: `ZyfNO2/PaperClaw`
- Baseline branch: `main`
- Baseline SHA at amendment start: `5ae85c31a148ed0c8dd7ecd2a70a4c63c41c0f74`
- Scope: v0.11 desktop frontend, Python bridge provider defaults, browser interaction tests, and CI only.

## Implemented changes

### Frontend

- Replaced the previous form-style desktop UI with the supplied PaperClaw console visual language.
- Preserved the concrete-gray surface, white border, hard-shadow, square-corner, monospaced design.
- Connected Console, Trace, Settings, workspace selection, New Run, Execute, Stop, Export Trace, filters, command chips, search, keyboard shortcuts, counters, progress, verification, final result, and event timeline interactions.
- Removed all remote font, Tailwind browser runtime, icon CDN, and Chart.js dependencies from the supplied draft.
- Kept CSP, local-only assets, no browser persistence, no `innerHTML`, no `eval`, and bounded rendered event history.

### Environment-backed LLM default

- JavaScript no longer receives or submits an API Key.
- `DesktopAPI.start_run()` hydrates missing provider fields from:
  - `PAPERCLAW_API_KEY`
  - `PAPERCLAW_BASE_URL`
  - `PAPERCLAW_MODEL`
  - `PAPERCLAW_PROVIDER` (optional)
- The selected workspace `.env` is loaded first; the process working-directory `.env` is then loaded without replacing explicit process environment values.
- Explicit provider fields remain supported for compatibility with direct Python callers.
- `DesktopAPI.get_defaults()` returns only non-secret provider status, base URL, model, provider, workspace, and missing-variable names.

## Playwright coverage

The browser suite injects a deterministic pywebview API double and validates actual DOM clicks and state transitions without calling a real Provider.

Covered interactions:

1. Initial environment/default rendering.
2. Settings dialog open/close.
3. Sidebar navigation and under-development feedback.
4. Workspace picker result propagation.
5. Sidebar collapse/expand.
6. Execute button and Enter-to-submit.
7. Exact run payload contract with no Key/Base URL/Model in JavaScript.
8. Run controls disabled during active execution.
9. Model/tool/verification event rendering and filtering.
10. Final result rendering.
11. Cooperative cancel button flow.
12. Empty-task validation.
13. Command-chip insertion and task clearing.
14. Mission-log search.
15. Trace JSON download.
16. New Run reset.

Local cloud-container result before commit:

```text
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
  pytest -q tests/e2e/desktop

4 passed
```

The system Chromium in the development container blocked direct `file://` and localhost navigation through administrator policy. The test harness therefore uses Playwright `page.set_content()` with the exact committed HTML/CSS/JavaScript inlined for test execution. GitHub Actions installs Playwright Chromium and runs the same interaction suite.

## Files changed

- `src/paperclaw/desktop/app.py`
- `src/paperclaw/desktop/static/index.html`
- `src/paperclaw/desktop/static/styles.css`
- `src/paperclaw/desktop/static/app.js`
- `tests/unit/desktop/test_app.py`
- `tests/unit/desktop/test_static_assets.py`
- `tests/e2e/desktop/conftest.py`
- `tests/e2e/desktop/test_console.py`
- `.github/workflows/desktop-playwright.yml`
- `pyproject.toml`

## Verification boundaries

### Verified

- Browser interaction logic with Playwright and a deterministic pywebview bridge double.
- JavaScript run payload excludes provider credentials and model endpoint fields.
- Environment hydration and non-secret defaults are covered by Python unit tests in CI.
- Static frontend contains only local resources and preserves the supplied design language.

### Pending

- GitHub Actions result on the amendment commit.
- Native pywebview rendering on Windows/WebView2.
- Packaged Windows executable launch after the frontend replacement.
- Real Provider execution using a disposable environment-backed credential.
- Real cancellation while a Provider/tool call is active.
- Credential search across UI, logs, trace, SQLite, stdout, and stderr after a real run.

## Required real acceptance

Configure `.env` in the selected workspace or process environment:

```dotenv
PAPERCLAW_API_KEY=...
PAPERCLAW_BASE_URL=https://provider.example/v1
PAPERCLAW_MODEL=provider-model-id
PAPERCLAW_PROVIDER=openai-compatible
```

Then run:

```powershell
python -m pip install -e ".[gui,dev]"
paperclaw gui
```

Confirm the initial header reports `LLM · ENV`, select a workspace, execute a harmless task, inspect the timeline/result, run a longer task and press Stop, and verify the full Key is absent from all visible and persisted outputs.
