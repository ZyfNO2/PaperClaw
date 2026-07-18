# PaperClaw v0.17 Consolidated Acceptance Evidence

## Current Release Status

**HOLD — awaiting real native Desktop revalidation.**

The original operator run covered the real LLM and protected browser interface, but did not exercise the native pywebview workspace picker. The earlier claim that all manual Desktop scenarios passed is superseded by `DESKTOP_WORKSPACE_PICKER_REVALIDATION.md`.

PR #42 must remain Draft until the native scenario passes and the Release Owner signs off.

## Historical Candidate

The automated evidence below was collected for:

```
58e7900dd80c1ad5645ab683c3cdeccf4388bea1
```

It remains valid historical evidence for unchanged subsystems, but it is not exact-head evidence for the native workspace-picker correction.

## Native Workspace Picker Correction

| Item | Commit |
|------|--------|
| Native candidate resolution, stale-window retry, and picker extension | `e29067cff6b05dd536081c22b092e00d0a529d5a` |
| Desktop bootstrap installation | `a2c044d5647e251120b09abc5e3a7edf3574b8b3` |
| Focused regression and bootstrap integration coverage | `0142e163cee80702e9334837177fccd65c96a857` |
| Native revalidation procedure | `c0c00319ffe790c6eac0bb494a13a784bc48d67a` |

Exact-head automated results are recorded in PR #42 after CI completion. Automated tests use fake native-window objects and cannot replace the required real Windows interaction.

## Historical Automated Gates

| Gate | Result | Evidence |
|------|--------|----------|
| Windows Main CI | 765 passed, 0 failed | `pytest-results-29627370327` |
| Windows Non-Process Regression | 763 passed, 0 failed | Same historical release chain |
| Real Process Recovery | 2 passed, 0 failed | `process-acceptance` workflow |
| Context/Memory Focused | 92 passed, 0 failed | `context-memory-focused-29627370326` |
| Desktop Playwright | 5 passed, 0 failed | `desktop-playwright-29627370335` |
| Ruff Correctness | PASS | Historical exact-head verification |
| Windows PyInstaller onedir | PASS | `PaperClaw-Windows-onedir-29627370338` |

## Manual Acceptance Scenarios

| # | Scenario | Current Result | Verification Method |
|---|----------|----------------|---------------------|
| 1 | Desktop First-Run Provider Config and native workspace picker | ⏳ PENDING | Must complete `DESKTOP_WORKSPACE_PICKER_REVALIDATION.md` on Windows |
| 2 | Workspace Credential Isolation | ✅ PASS | API testing with workspace-A/B |
| 3 | Project Instructions | ✅ PASS | API testing with @ imports |
| 4 | Context Compaction | ✅ PASS | Unit tests (4/4 passed) |
| 5 | User Profile and Long Memory | ✅ PASS | Script testing |
| 6 | Memory Privacy and Concurrency | ✅ PASS | Script testing |
| 7 | Service API Durability | ✅ PASS | Integration tests (11/11 passed) |
| 8 | Service Personal Memory Boundary | ✅ PASS | Unit tests (3/3 passed) |
| 9 | Tool Authorization | ✅ PASS | Script testing |
| 10 | Research Evaluation | ✅ PASS | Unit tests (6/6 passed) |

## Code Review

- Historical Critical/High: 0
- Historical Medium: 1 (`reject_secret_like_fields` dead code)
- New reported defect: native workspace selection was not covered by the original operator acceptance
- Current disposition: implementation corrected; real native behavior not yet verified

## Entry Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | PR #42 targets main and is mergeable | ✅ |
| 2 | Only one consolidated PR open | ✅ |
| 3 | Exact-head automated workflows complete | ⏳ PENDING until current CI finishes |
| 4 | No Critical/High open | ⏳ PENDING final exact-head review |
| 5 | Native Desktop workspace picker verified on Windows | ⏳ PENDING |
| 6 | No real credentials in repo | ✅ |
| 7 | Release Owner sign-off | ⏳ PENDING |

## Release Decision

**HOLD** — do not mark PR #42 ready and do not merge. The code correction and automated regression suite must pass at the current head, then the real native Desktop procedure must pass before Release Owner sign-off.
