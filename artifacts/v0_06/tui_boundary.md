# v0.06 TUI Runtime Boundary

## Allowed dependencies

```text
paperclaw.tui
→ paperclaw.harness public contracts
→ paperclaw.models adapter only inside engine factory
→ Textual / Rich presentation primitives
```

## Forbidden direct dependencies

- `paperclaw.tools.*`
- `paperclaw.context.*` Repository / Session internals
- `sqlite3` or schema/table access
- Agent prompt construction
- Permission decisions
- direct model/tool execution from widgets

An AST-based unit test enforces the Tool/Repository/SQLite import boundary.

## Event contract

Accepted timeline events:

```text
run.started
model.started / model.completed / model.failed
tool.started / tool.completed / tool.failed
verification.completed
permission.denied
run.stop_requested
run.completed / run.failed / run.stopped
```

Unknown QueryEngine events are rendered only as event name plus sequence. Arbitrary payload content is not rendered. Legacy reasoning events are not admitted by the bridge.

## Ordering

The reducer requires:

- non-empty `run_id`;
- positive integer `sequence`;
- one run at a time;
- strictly increasing sequence;
- no state update after terminal.

Rejected stale/duplicate events do not mutate visible status.

## Fallback contract

- `Textual` missing: print reason; use CLI when a task is supplied.
- stdin/stdout not TTY: same fallback behavior.
- `--no-tui`: explicit fallback.
- no task available: return exit code 2 with a concrete `paperclaw agent <task>` instruction.
