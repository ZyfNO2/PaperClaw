# PaperClaw v0.17 Consolidated Release Acceptance Report

## Executive Summary

**Current decision: HOLD / NOT READY FOR RELEASE.**

The original v0.17 operator run validated the real LLM and protected browser interface, but did not exercise the native pywebview workspace picker used by `select_workspace()`. The previous `ACCEPT pending Release Owner sign-off` recommendation is withdrawn.

A code correction and focused automated tests have been added to PR #42. The release remains blocked until:

1. all exact-head automated workflows pass;
2. the real Windows native workflow in `DESKTOP_WORKSPACE_PICKER_REVALIDATION.md` passes;
3. the Technical Reviewer and Release Owner sign off.

PR #42 must remain Draft and must not be merged before those conditions are met.

---

## Reported Defect

### Native workspace picker requires a live window

The prior implementation depended only on the `DesktopAPI._window` reference. The original manual acceptance did not launch and exercise the native Desktop path, so it did not detect failures involving a missing, stale, hidden, or minimized pywebview window.

The protected browser interface does not remove the native dependency: its `select_workspace()` request still requires a native pywebview `Window` to display the folder dialog.

---

## Implemented Correction

The Desktop bootstrap now installs a focused native workspace-picker extension that:

- uses the window bound by `run_desktop()` when valid;
- falls back to `webview.active_window()` and the pywebview window registry;
- shows and restores the native host before opening the dialog;
- retains pywebview 5 and 6 folder-dialog compatibility;
- returns `native_window_required` when no native window exists;
- preserves cancellation and workspace path validation behavior.

Primary implementation and evidence:

- `src/paperclaw/desktop/native_workspace.py`
- `src/paperclaw/desktop/bootstrap.py`
- `tests/unit/desktop/test_native_workspace.py`
- `artifacts/v0_17_acceptance/DESKTOP_WORKSPACE_PICKER_REVALIDATION.md`

---

## Automated Evidence Boundary

The focused regression tests verify native-window resolution and control flow using fake pywebview objects. They do not create a real OS window or native folder dialog.

Desktop Playwright remains a browser interaction gate with a mocked JavaScript bridge. Windows packaging verifies build and packaged assets. Neither gate alone proves that a real folder dialog is visible and interactive.

Exact-head workflow results are recorded in PR #42 after the current CI completes.

---

## Historical Automated Results

The following results were collected at historical candidate `58e7900dd80c1ad5645ab683c3cdeccf4388bea1`:

| Gate | Historical Result |
|------|-------------------|
| Windows Main CI | 765 passed, 0 failed, 5 setup-skipped |
| Windows Non-Process Regression | 763 passed, 0 failed, 5 setup-skipped |
| Real Process Recovery | 2 passed, 0 failed |
| Context/Memory Focused | 92 passed, 0 failed |
| Desktop Playwright | 5 passed, 0 failed |
| Ruff Correctness | PASS |
| Windows PyInstaller onedir | PASS |

These results remain useful for unchanged subsystems, but they are not exact-head proof for the native workspace-picker correction.

---

## Manual Scenario Status

| # | Scenario | Status |
|---|----------|--------|
| 1 | Desktop first-run, native workspace picker, and real-LLM run | **PENDING** |
| 2 | Workspace credential isolation | PASS |
| 3 | Project instructions | PASS |
| 4 | Context compaction | PASS |
| 5 | User profile and long memory | PASS |
| 6 | Memory privacy and concurrency | PASS |
| 7 | Service API durability | PASS |
| 8 | Service personal-memory boundary | PASS |
| 9 | Tool authorization | PASS |
| 10 | Research evaluation | PASS |

Scenario 1 must be rerun in the native Windows application according to `DESKTOP_WORKSPACE_PICKER_REVALIDATION.md`.

---

## Current Sign-Off

| Role | Status |
|------|--------|
| Test Operator | Previous web/real-LLM run complete; native rerun pending |
| Technical Reviewer | Pending exact-head review |
| Release Owner | Pending after native acceptance |

---

## Release Decision

### HOLD

The release is not accepted at this time. Automated success cannot substitute for the missing real native-window interaction. After exact-head CI passes, complete the native Windows revalidation and attach the requested screenshots, console output, and diagnostics before changing this decision.
