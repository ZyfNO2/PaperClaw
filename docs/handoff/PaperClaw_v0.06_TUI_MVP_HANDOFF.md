# PaperClaw v0.06 TUI MVP Handoff

## Status

**WAITING REAL TERMINAL ACCEPTANCE**

Implementation, focused offline validation, full automated CI, SQLite Doctor and the live-provider QueryEngine path are complete. Physical Windows Terminal interaction, TUI resize, Inspector readability and live TUI cancellation remain pending.

## Repository and branch

- Repository: `ZyfNO2/PaperClaw`
- Base: `main` at `5b83e67df1ce2742495ae67ec225b60aa8bcb6ee`
- Branch: `feat/v0.06-tui-mvp`
- Draft PR: `#2`
- Implementation/test HEAD before documentation closeout: `07cacdff573cd53b93d247f677c0f0841d7463f4`
- Final branch HEAD: see Draft PR and final development report; this Handoff file is part of the final closeout commit.

## Completed

- Optional Textual installation path.
- `paperclaw tui` CLI entry.
- Four-widget full-screen MVP.
- Worker-thread QueryEngine adapter.
- Ordered bridge/reducer and terminal-state protection.
- Four MVP slash commands.
- Cooperative cancellation and duplicate-submit handling.
- CLI fallback paths.
- Narrow-layout behavior.
- Offline/headless tests and architecture-boundary test.
- Windows full regression and Ruff CI.
- SOP, artifacts and implementation boundary documentation.

## Main files

- `src/paperclaw/tui/app.py`
- `src/paperclaw/tui/bridge.py`
- `src/paperclaw/tui/state.py`
- `src/paperclaw/tui/runner.py`
- `src/paperclaw/tui/widgets.py`
- `src/paperclaw/tui/paperclaw.tcss`
- `src/paperclaw/cli.py`
- `pyproject.toml`
- `tests/unit/test_tui_*.py`
- `artifacts/v0_06/*`

## Key architecture decisions

- Keep QueryEngine synchronous; use a Textual worker thread.
- Keep Textual optional and lazy-loaded.
- Do not allow widgets to execute Tool, access Repository/SQLite or construct Prompt.
- Use a narrow verification-event bridge instead of expanding QueryEngine or creating an EventBus.
- Use UI-local sequence ordering; reject stale/duplicate/post-terminal events.
- Treat cancellation as cooperative only.

## Tests and CI

- Focused local fixture: `10 passed`.
- GitHub Actions run: `29361795132`.
- Windows full pytest: `376 passed`, `0 failed`, `0 skipped`.
- Ruff E9/F63/F7/F82: PASS.
- Real interactive E2E: not run.

### Local acceptance supplement (2026-07-15)

- Windows 11 build `26200`; Windows Terminal `1.24.11321.0`;
- Python `3.13.5`; Textual `7.5.0`;
- SQLite Doctor quick/integrity checks: PASS, schema version 3;
- live-provider QueryEngine create/run/verify: `1 passed in 31.12s`;
- live-provider cooperative cancel: `1 passed in 19.04s`, ending as `stopped / user_requested` with one `run.stopped` event;
- sanitized evidence: `artifacts/v0_06/real_acceptance/acceptance_report.md`.
- physical wide-terminal screenshot: `artifacts/v0_06/real_acceptance/windows_terminal_wide.png`.

The live-provider tests cover backend create/run/verify and the cancellation race. The supplied Windows Terminal screenshot separately confirms physical TUI launch, task completion and Inspector rendering. Narrow resize and a post-fix physical TUI `/cancel` capture remain pending.

## Known limitations

See `artifacts/v0_06/known_limitations.md`. The most important limitation is that `/cancel` cannot forcibly interrupt an already-running synchronous provider or shell call.

## Exact manual acceptance steps

### Prepare

```powershell
git fetch origin
git switch feat/v0.06-tui-mvp
python -m pip install -e ".[dev,tui]"
$env:PAPERCLAW_API_KEY = "<real key>"
$env:PAPERCLAW_BASE_URL = "<provider base URL>"
$env:PAPERCLAW_MODEL = "<model>"
```

### Test A — launch and resize

```powershell
paperclaw tui --workspace .
```

Expected:

- full-screen app launches;
- RunStatus at top, prompt at bottom;
- at wide width Chat and Timeline are side by side;
- below 80 columns they stack vertically;
- resize does not crash or corrupt input.

### Test B — live task

Enter:

```text
创建 hello.py，使其输出 PaperClaw v0.06 OK，并运行验证
```

Expected:

- status changes idle → running → terminal;
- timeline contains run/model/tool/verification lifecycle rows;
- final output, status, stop_reason and call counters appear;
- `hello.py` exists and was actually run/verified.

### Test C — cooperative cancel

Start a task likely to take multiple steps, then enter:

```text
/cancel
```

Expected:

- UI prints that cancellation is cooperative;
- timeline contains `run.stop_requested`;
- app remains responsive;
- run eventually reaches a terminal state at a safe boundary.

Do not fail the test merely because an already-started provider or shell call finishes before cancellation is observed. Fail it if no stop request is emitted, the UI freezes permanently, or a later event overwrites terminal state.

### Test D — fallback

```powershell
paperclaw tui "直接结束并输出 fallback-ok" --no-tui --workspace .
```

Expected:

- stderr explains CLI fallback;
- stdout is the standard JSON payload;
- existing `paperclaw agent` behavior remains intact.

## Return artifacts

Return or commit, after secret redaction:

- Windows version and terminal version;
- Python/Textual versions;
- terminal screenshots at wide and narrow widths;
- complete structured timeline or sanitized log;
- final RunResult JSON;
- generated `hello.py` and verification output;
- cancel test timing and terminal state;
- any traceback or corrupted-screen screenshot.

## Pass/fail decision

PASS only when Test A–D succeed and artifacts contain no secret. Otherwise keep status `WAITING REAL TERMINAL ACCEPTANCE` or change to `REQUEST CHANGES` with the exact failure trace.

## Next developer steps

1. Run the remaining physical-terminal parts of the manual acceptance above (launch/resize, Inspector readability, TUI task and `/cancel`).
2. Add sanitized evidence under `artifacts/v0_06/real_terminal/`.
3. Update the SOP Gate M06-11 and real-task requirements.
4. Change overall status to GO only after evidence review.
5. Keep PR as Draft until that review; do not merge automatically.
