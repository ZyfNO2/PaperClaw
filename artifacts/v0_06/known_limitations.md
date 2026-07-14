# PaperClaw v0.06 TUI MVP — Known Limitations

## Runtime limitations

- `QueryEngine.submit()` remains synchronous; Textual uses a worker thread rather than an async runtime rewrite.
- `/cancel` is cooperative. It does not forcibly interrupt an active provider request, shell process or process tree.
- Only one run may be active in a TUI conversation.
- No token or stdout/stderr streaming.
- Verification events currently enter through a narrow legacy-event bridge.

## Product limitations

- No Permission Dialog or allow-once/session decisions.
- No Session Picker, reconnect or crash reconciliation.
- No Context, Trace, Cost or dedicated Verification inspector.
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
