# PaperClaw v0.06 TUI MVP — Known Limitations

## Runtime limitations

- `QueryEngine.submit()` remains synchronous; Textual uses a worker thread rather than an async runtime rewrite.
- `/cancel` is cooperative. It does not forcibly interrupt an active provider request or an arbitrary Tool.
- `BashTool` is an exception: it polls `ToolContext.stop_token` every 200ms and attempts best-effort process-tree termination via `taskkill /T /F` (falling back to `process.kill()`). This is not a general forced-cancellation mechanism and does not guarantee cleanup of all child processes.
- Only one run may be active in a TUI conversation.
- No token or stdout/stderr streaming.
- Verification events currently enter through a narrow legacy-event bridge.

## Product limitations

- No Permission Dialog or allow-once/session decisions.
- No Session Picker, reconnect or crash reconciliation.
- No Context, Trace or Cost inspector. The original v0.06 MVP had no dedicated Verification inspector; the current branch's v0.06.1 slice adds one sanitized aggregate-only Verification Inspector.
- No MultiAgent task/DAG view.
- No Web UI/API or daemon.
- No clipboard redaction or full accessibility matrix.

## Validation limitations

The following remain `PENDING / NOT VERIFIED`:

- interactive Windows Terminal launch and keyboard behavior;
- real resize behavior in a physical terminal;
- live-provider task completion through the TUI;
- live `/cancel` timing while a provider or shell call is in progress;
- real screenshot/log artifact capture and redaction review.

Headless Textual tests, FakeEngine tests and GitHub Actions are not represented as real interactive E2E.
