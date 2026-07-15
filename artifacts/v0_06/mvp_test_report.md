# PaperClaw v0.06 TUI MVP — Test Report

## Status

`WAITING REAL TERMINAL ACCEPTANCE`

PR #2 is merged, but the v0.06 acceptance gate is not GO. Draft PR #4 repairs the missing Tool `execute()` cancellation-race coverage and synchronizes acceptance evidence.

## Automated evidence

| Layer | Code provenance | Command / environment | Result |
|---|---|---|---|
| Original final source-head regression | `d5d43e3cd74e80d35190e16253446f37841a4b2e` | GitHub Actions Windows run `29413807619` / #45 | 382 call-phase tests passed |
| Original source-head static lint | `d5d43e3...` | Ubuntu Ruff E9/F63/F7/F82 | PASS |
| Repair focused test | Draft PR #4 | `python -m pytest tests/unit/test_agent_runtime_executor.py -q` | PENDING CI |
| Repair full regression | Draft PR #4 | Windows GitHub Actions | PENDING CI |
| Repair static lint | Draft PR #4 | Ruff high-signal checks | PENDING CI |

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
- unrelated runtime failure after stop remains `runtime_failed`;
- Tool `execute()` exception-after-stop translation in Draft PR #4.

## Repair regression contract

The new deterministic Tool fixture must prove:

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

This test closes the missing adapter path. It does not authorize translating arbitrary AgentRuntime, Session, Repository or persistence failures into cancellation.

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

1. Draft PR #4 CI passes.
2. Physical Windows Terminal width below 80 columns passes.
3. Post-fix physical TUI `/cancel` reaches one truthful terminal state.
4. Doctor quick/full passes against a safe real or sanitized database copy.
5. Handoff, SOP, acceptance report and this report identify the same final repair commit and CI run.

Do not mark v0.06 GO before all required gates are reviewed.
