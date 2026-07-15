# PaperClaw v0.06 TUI MVP — Test Report

## Automated results

| Layer | Command / environment | Result |
|---|---|---|
| Focused TUI tests | isolated local fixture | `10 passed` |
| Full regression | GitHub Actions Windows, run `29361795132` | `376 passed, 0 failed, 0 skipped` |
| Static lint | GitHub Actions Ubuntu Ruff E9/F63/F7/F82 | PASS |

## v0.06 focused coverage

- reducer monotonicity and post-terminal protection;
- unknown-event payload suppression;
- QueryEngine/verification bridge ordering;
- legacy reasoning-event exclusion;
- Textual headless launch and four-widget composition;
- narrow-width single-column layout;
- completed terminal result rendering;
- active-run duplicate-submit rejection;
- cooperative `/cancel` request and stopped result;
- no-TTY fallback;
- missing-Textual fallback;
- explicit `--no-tui` CLI integration;
- architecture import boundary.

## Existing regression evidence

The full suite also covers QueryEngine terminal uniqueness, budget enforcement, Tool validation, Session/SQLite behavior, Verify/Reflection, MultiAgent and legacy single-agent CLI compatibility.

## Test classification

- Headless Textual and FakeEngine tests: **offline control-flow/UI-state validation**.
- GitHub Actions Windows suite: **automated platform regression**, not interactive terminal E2E.
- Live-provider interactive TUI: **not executed / pending**.

## Pending manual acceptance

1. Launch in Windows Terminal with Textual installed.
2. Verify wide and narrow layouts.
3. Complete one live create/run/verify task.
4. Start a second task and issue `/cancel` during active work.
5. Capture sanitized environment, screenshots, terminal output and final RunResult.

## 2026-07-15 local acceptance supplement

- SQLite Doctor quick/integrity checks: PASS, schema version 3.
- Live Provider QueryEngine create/run/verify: `1 passed in 31.12s`.
- Live Provider cooperative cancel regression: `1 passed in 19.04s`; terminal status `stopped`, reason `user_requested`, unique event `run.stopped`.
- Environment: Windows 11 build 26200, Windows Terminal 1.24.11321.0, Python 3.13.5, Textual 7.5.0.
- Evidence: `artifacts/v0_06/real_acceptance/acceptance_report.md`.

This closes the live backend cancellation regression that previously surfaced as `runtime_failed`. It does not replace the remaining physical-terminal resize and screenshot evidence or the real/sanitized user-database Doctor gate.
