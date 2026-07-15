# PaperClaw v0.06 TUI MVP — Test Report

## Status

`WAITING REAL TERMINAL ACCEPTANCE`

PR #2 is merged. Draft PR #4 closes the missing Tool `execute()` cancellation-race coverage and has passed automated CI. The remaining gates are physical narrow resize, post-fix physical TUI `/cancel`, and safe real/sanitized database Doctor evidence.

## Automated evidence

| Layer | Code provenance | Command / environment | Result |
|---|---|---|---|
| Original final source-head regression | `d5d43e3cd74e80d35190e16253446f37841a4b2e` | GitHub Actions Windows run #45 | 382 call-phase tests passed |
| Original source-head static lint | `d5d43e3...` | Ubuntu Ruff E9/F63/F7/F82 | PASS |
| Repair focused + full regression | `8e27bdcf908c9fbc81a726cd1dfb9fa82c13eb82` | GitHub Actions Windows run `29417443436` / #71 | 383 passed, 0 failed, 0 skipped |
| Repair static lint | `8e27bdcf...` | Ruff high-signal checks | PASS |
| Repair artifact | `8e27bdcf...` | `pytest-results-29417443436` | available |

## Focused coverage

- reducer monotonicity and post-terminal protection;
- unknown-event payload suppression;
- QueryEngine/verification bridge ordering;
- legacy reasoning-event exclusion;
- Textual headless launch and widget composition;
- narrow-width single-column layout implementation;
- completed/stopped terminal rendering;
- active-run duplicate-submit rejection;
- cooperative `/cancel` request;
- no-TTY, missing-Textual and explicit `--no-tui` fallback;
- architecture import boundary;
- Provider exception-after-stop translation;
- Tool `execute()` exception-after-stop translation;
- unrelated runtime failure after stop remains `runtime_failed`.

## Repair regression contract

The deterministic Tool fixture passed as part of run #71 and proves:

```text
tool.started
→ request_stop(user_requested)
→ in-flight Tool execute raises RuntimeError
→ tool.failed / TOOL_EXECUTION_FAILED remains observable
→ final status stopped
→ stop_reason user_requested
→ tool_calls == 1
→ exactly one terminal event: run.stopped
```

This closes the missing adapter path. It does not authorize translating arbitrary AgentRuntime, Session, Repository or persistence failures into cancellation.

## Evidence classification

- Headless Textual and FakeEngine tests: offline control-flow/UI-state validation.
- Windows CI: automated platform regression, not physical terminal E2E.
- Live-provider QueryEngine tests: backend integration, not physical TUI interaction.
- Historical wide screenshot: physical evidence for launch/task/Inspector on the recorded older HEAD.
- Physical narrow resize and post-fix TUI `/cancel`: still pending.
- Fixture Doctor: storage smoke only, not a real/sanitized user database gate.

## Historical live acceptance

- SQLite migrated-fixture Doctor quick/full: PASS, schema version 3.
- Live Provider create/run/verify: `1 passed in 31.12s`.
- Live Provider normal safe-boundary cancel: `1 passed in 19.04s`, ending `stopped / user_requested` with one `run.stopped`.
- Environment: Windows 11 build 26200, Windows Terminal 1.24.11321.0, Python 3.13.5, Textual 7.5.0.
- Evidence: `artifacts/v0_06/real_acceptance/acceptance_report.md`.

The normal backend cancel test does not reproduce the original physical TUI `runtime_failed` signature and cannot replace the post-fix physical capture.

## Remaining gates

1. Physical Windows Terminal width below 80 columns passes.
2. Post-fix physical TUI `/cancel` reaches one truthful terminal state.
3. Doctor quick/full passes against a safe real or sanitized database copy.
4. Final evidence review confirms no secret and consistent status.

Do not mark v0.06 GO before all required gates are reviewed.
