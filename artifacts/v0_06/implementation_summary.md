# PaperClaw v0.06 TUI MVP — Implementation Summary

## Status

`Implementation complete / offline validation passed / waiting real terminal and live-provider acceptance`.

## Implemented slice

- Optional Textual dependency (`.[tui]`), also installed by `.[dev]` for CI.
- `paperclaw tui [task]` entrypoint and `--no-tui` fallback.
- Four functional widgets: `ChatLog`, `PromptInput`, `RunStatus`, `ToolTimeline`.
- Worker-thread execution of the existing synchronous `QueryEngine.submit()`.
- Single-active-run gate, duplicate-submit rejection, `/help`, `/new`, `/cancel`, `/quit`.
- UI-local ordered event bridge and deterministic reducer.
- Structured output/status/call-counter rendering.
- Missing Textual, no-TTY and explicit fallback paths.
- Narrow-terminal single-column layout.

## Architecture decisions

### Thin client, not a second runtime

The TUI depends on the public Harness contracts and does not import concrete Tools, Repository classes, database tables or Prompt construction. Runtime truth remains in `QueryEngine` and `RunResult`.

### Optional dependency boundary

Textual imports are delayed until after terminal and dependency checks. The existing `paperclaw agent` path therefore keeps the original dependency surface.

### Verification event bridge

QueryEngine already owns ordered run/model/tool lifecycle events, while verification is still exposed through the legacy runtime observer. `TUIEventBridge` admits only `verification_completed`, drops reasoning events, assigns a UI-local monotonic sequence and preserves the original sequence as `query_sequence`.

### Cooperative cancellation

`/cancel` calls `QueryEngine.request_stop(active_run_id)`. The UI explicitly states that an in-flight synchronous provider or arbitrary Tool call can continue until the next safe boundary.

`BashTool` adds a narrow exception: it polls `ToolContext.stop_token` every 200ms while a PowerShell subprocess is running and performs best-effort process-tree termination if cancellation is detected. This is still best-effort and does not generalize to provider calls or other Tools.

## Reference use

The implementation reused PaperClaw's existing QueryEngine, CLI vocabulary and runtime event contracts. Reference projects were used only for interaction-state and stale-propagation lessons; no external UI module or source block was copied.

## Deliberately not implemented

Permission UX, shell streaming/background tasks, Session Picker, inspector panels, MultiAgent visualization, Web UI/API, daemon mode and forced process-tree cancellation remain in v0.06.1.
