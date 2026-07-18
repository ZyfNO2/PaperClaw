# Native Desktop Workspace Picker Revalidation

## Status

`PENDING REAL NATIVE DESKTOP TEST`

## Reported acceptance gap

The original v0.17 operator run exercised the real LLM and the protected browser interface, but did not exercise the packaged/native pywebview workspace-selection path. The browser interface can request `select_workspace()`, but a folder dialog ultimately requires a live native pywebview `Window`.

The previous acceptance claim for the complete Desktop first-run scenario is therefore superseded by this addendum until the native steps below are completed.

## Implemented correction

- install the picker through the existing Desktop bootstrap extension pattern;
- use the window bound by `run_desktop()` when it supports native dialogs;
- recover from `webview.active_window()` or `webview.windows` when the stored binding is absent or stale;
- show and restore the native host before opening the folder dialog;
- return the typed `native_window_required` error when no native window exists;
- preserve pywebview 5 and 6 folder-dialog compatibility;
- keep cancellation non-destructive.

## Automated evidence boundary

Focused tests cover:

- extension installation and idempotency;
- bound native-window selection;
- active-window and window-registry recovery;
- show/restore/dialog ordering;
- cancellation;
- typed failure without a native window.

These tests use fake pywebview objects. They verify control flow, but they do **not** constitute a real native GUI acceptance result.

## Required Windows acceptance

From the PR branch:

```powershell
git fetch origin
git checkout feat/v0.17-context-long-memory
git pull --ff-only
python -m pip install -e ".[gui,dev]"
python -m pytest -q tests/unit/desktop/test_app.py tests/unit/desktop/test_native_workspace.py tests/unit/desktop/test_static_assets.py
paperclaw gui
```

In the native PaperClaw window:

1. Click the workspace card or **Select Workspace**.
2. Confirm a native folder dialog appears in front of PaperClaw.
3. Cancel the dialog once and confirm the previous workspace remains selected with no public error.
4. Select a real workspace containing a valid `.env`.
5. Confirm the displayed absolute workspace path changes to the selected directory.
6. Start one real-LLM run and confirm it reaches a terminal state.
7. Open protected browser mode and trigger workspace selection there.
8. Confirm the native PaperClaw host is shown/restored and the folder dialog remains visible in front.

## Pass criteria

- native-window and protected-browser triggers both open one visible native folder dialog;
- selected absolute path is reflected in the UI;
- cancellation is non-destructive;
- no hidden dialog, frozen UI, `native_window_required`, or `runtime_error` occurs while the native application is running;
- a real-LLM run succeeds using the selected workspace.

## Evidence to return

Return:

- the focused pytest output;
- a screenshot showing the native dialog in front of PaperClaw;
- a screenshot of the selected workspace and terminal run state;
- console output;
- any relevant diagnostic log under `~/.paperclaw/` if a failure occurs.

## Release impact

PR #42 remains Draft. Release status is **HOLD / awaiting real native Desktop revalidation**; Release Owner sign-off alone is not sufficient until this scenario passes.
