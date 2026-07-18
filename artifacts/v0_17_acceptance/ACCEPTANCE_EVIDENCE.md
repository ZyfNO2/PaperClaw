# PaperClaw v0.17 Consolidated Acceptance Evidence

## Candidate SHA

```
58e7900dd80c1ad5645ab683c3cdeccf4388bea1
```

## Acceptance Date

2026-07-18

## Automated Gates

| Gate | Result | Evidence |
|------|--------|----------|
| Windows Main CI | 765 passed, 0 failed | `pytest-results-29627370327` |
| Windows Non-Process Regression | 763 passed, 0 failed | Same artifact |
| Real Process Recovery | 2 passed, 0 failed | `process-acceptance` workflow |
| Context/Memory Focused | 92 passed, 0 failed | `context-memory-focused-29627370326` |
| Desktop Playwright | 5 passed, 0 failed | `desktop-playwright-29627370335` |
| Ruff Correctness | PASS | Local verification |
| Windows PyInstaller onedir | PASS | `PaperClaw-Windows-onedir-29627370338` |

## Manual Acceptance Scenarios

| # | Scenario | Result | Verification Method |
|---|----------|--------|---------------------|
| 1 | Desktop First-Run Provider Config | ✅ PASS | Manual verification with screenshots |
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

- Critical/High: 0
- Medium: 1 (dead code: `reject_secret_like_fields`)
- Low: 0

## Entry Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | PR #42 targets main, mergeable | ✅ |
| 2 | Only one consolidated PR open | ✅ |
| 3 | Exact-head workflows complete | ✅ |
| 4 | No Critical/High open | ✅ |
| 5 | Artifacts identify same SHA | ✅ |
| 6 | Working tree clean | ✅ |
| 7 | No real credentials in repo | ✅ |

## Release Decision

**ACCEPT** — All automated gates pass, all manual scenarios pass, no open Critical or High issue.
