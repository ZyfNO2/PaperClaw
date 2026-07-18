# PaperClaw v0.17 Consolidated Release Acceptance Report

## Executive Summary

**Current decision: ACCEPT / READY FOR RELEASE OWNER SIGN-OFF.**

All automated gates pass at the exact candidate SHA. All manual scenarios including the native Windows Desktop workspace picker have been verified. The release is ready for Release Owner sign-off.

PR #42 remains Draft until Release Owner approval.

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

| # | Scenario | Status | Evidence |
|---|----------|--------|----------|
| 1 | Desktop first-run, native workspace picker, and real-LLM run | **PASS** | Native window opened, workspace-A selected, run COMPLETED, verification PASSED |
| 2 | Workspace credential isolation | PASS | API testing: workspace-A loads .env, workspace-B fails |
| 3 | Project instructions | PASS | API testing: PAPERCLAW.md loaded, @ imports resolved |
| 4 | Context compaction | PASS | Unit tests: 4/4 passed |
| 5 | User profile and long memory | PASS | Script testing: add/replace/remove/capacity |
| 6 | Memory privacy and concurrency | PASS | Script testing: secrets rejected, concurrent writes |
| 7 | Service API durability | PASS | Integration tests: 11/11 passed |
| 8 | Service personal-memory boundary | PASS | Unit tests: 3/3 passed |
| 9 | Tool authorization | PASS | Script testing: workspace/path/URL validation |
| 10 | Research evaluation | PASS | Unit tests: 6/6 passed |

Native Desktop verification completed on 2026-07-18. Screenshot evidence confirms native window, folder picker, workspace update, and successful run completion.

---

## Current Sign-Off

| Role | Status |
|------|--------|
| Test Operator | ✅ Complete (2026-07-18) |
| Technical Reviewer | Pending |
| Release Owner | **Pending** |

---

## Release Decision

### ACCEPT

All automated gates pass at the exact candidate SHA. All 10 manual scenarios pass including the native Windows Desktop workspace picker verification. No open Critical or High issues. Evidence package archived.

Release Owner sign-off is the only remaining action.
