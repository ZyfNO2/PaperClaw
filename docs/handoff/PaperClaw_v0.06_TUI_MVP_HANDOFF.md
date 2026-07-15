# PaperClaw v0.06 TUI MVP Handoff

## Status

**WAITING REAL TERMINAL ACCEPTANCE**

PR #2 has been merged into `main`, but merge state is not acceptance GO. The implementation and repair CI are complete. Three physical/data gates remain open:

- physical Windows Terminal width below 80 columns;
- post-fix physical TUI `/cancel` capture;
- Doctor quick/full checks against a safe real or sanitized database copy.

## Repository state

- Repository: `ZyfNO2/PaperClaw`
- Base: `main`
- PR #2: merged on 2026-07-15
- PR #2 source HEAD: `d5d43e3cd74e80d35190e16253446f37841a4b2e`
- Main integration commit: `3804f72bbf0217c904c01dfabbcd046e3d930ca8`
- Repair branch: `fix/v0.06-acceptance-cancel-race`
- Repair PR: Draft PR #4
- Repair implementation/test HEAD: `9b339c78aaef65b16681204bc6c1b8ead457d8f9`
- Repair CI: run `29429703200` / #83 — SUCCESS
- Windows pytest: 388 passed, 0 failed, 0 skipped
- Ruff high-signal checks: PASS
- Artifact: `pytest-results-29429703200`

The historical source branch `feat/v0.06-tui-mvp` is not the current acceptance authority. Use `main` plus Draft PR #4.

## Implemented scope

- optional Textual installation and `paperclaw tui` entry;
- ChatLog, PromptInput, RunStatus, ToolTimeline and sanitized Verification Inspector;
- Textual worker wrapping synchronous `QueryEngine.submit()`;
- one active run, duplicate-submit rejection and cooperative stop request;
- `/help`, `/new`, `/cancel`, `/quit`;
- UI-local monotonic event reducer with stale, duplicate and post-terminal rejection;
- no-TTY, missing-Textual and explicit `--no-tui` fallback;
- narrow-layout implementation and headless layout test;
- read-only SQLite Doctor;
- adapter-scoped cancellation-race handling.

## Cancellation ownership

`/cancel` remains cooperative at the QueryEngine/adapter level. It does not forcibly interrupt a synchronous provider call or an arbitrary Tool.

Only adapter calls already in flight may translate a post-stop exception into cooperative control flow:

- provider `complete()`;
- Tool `validate()` for non-validation runtime exceptions;
- Tool `execute()`.

`BashTool` is a special case: it now polls `ToolContext.stop_token` every 200ms while a PowerShell subprocess is running. If cancellation is detected, it makes a best-effort attempt to terminate the process tree via `taskkill /T /F`, falling back to `process.kill()`. This is cooperative polling plus best-effort subprocess cleanup; it does not make the underlying provider call forcibly interruptible and does not generalize to all Tools.

The original sanitized failure event is emitted before translation. Unrelated AgentRuntime, Session, Repository and persistence exceptions remain `runtime_failed`, even when a stop token was accepted concurrently.

## Evidence matrix

| Gate | Status | Code provenance | Evidence / boundary |
|---|---|---|---|
| Original PR #2 source-head Windows CI | PASS | `d5d43e3...` | run #45; 382 call-phase tests passed; Ruff passed |
| Repair PR Windows CI | PASS | `9b339c78...` | run #83; 388 passed; Ruff passed |
| Provider exception-after-stop race | PASS | PR #2 source | deterministic adapter test |
| Tool `execute()` exception-after-stop race | PASS | `9b339c78...` | deterministic blocking Tool fixture in run #83 |
| Unrelated runtime failure after stop | PASS | `9b339c78...` | remains `runtime_failed` |
| Windows Terminal wide launch | PASS, historical physical | original evidence reports `0ef5b0b...` | `windows_terminal_wide.png` |
| Physical live create/run/verify task | PASS, historical | original acceptance record | does not prove post-repair cancel |
| Verification Inspector readability | PASS, historical | original acceptance record | aggregate visible; raw observed output absent |
| Windows Terminal narrow resize | PENDING MANUAL | — | physical screenshot below 80 columns required |
| Physical post-fix TUI `/cancel` | PENDING MANUAL | — | original screenshot ended `runtime_failed`; recapture required |
| SQLite migrated-fixture Doctor | PASS, smoke only | original acceptance record | not a user database gate |
| Safe real/sanitized DB Doctor | PENDING MANUAL | — | quick/full redacted JSON required |

## Automated commands

```powershell
python -m pip install -e ".[dev,tui]"
python -m pytest tests/unit/test_agent_runtime_executor.py -q
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## Remaining physical acceptance

### A. Narrow resize

```powershell
paperclaw tui --workspace .
```

Resize below 80 columns and confirm Chat and Timeline stack vertically, input remains usable, and no crash or screen corruption occurs. Return a sanitized screenshot showing the width.

### B. Post-fix physical `/cancel`

Start a multi-step task and enter:

```text
/cancel
```

Required evidence:

- `run.stop_requested` is visible;
- UI remains responsive;
- final state is reached at a safe boundary;
- an exception from an already-running provider or Tool is not mislabeled `runtime_failed`;
- exactly one terminal run event is present.

A successful backend or deterministic adapter test does not replace this physical TUI capture.

### C. Safe database Doctor

Run only against a non-unique copy or sanitized database:

```powershell
paperclaw doctor --database path\to\copy.db
paperclaw doctor --database path\to\copy.db --full
```

Return redacted JSON. Do not run automatic repair or migration as part of this gate.

## Acceptance decision

`GO` requires narrow physical resize, post-fix physical TUI `/cancel`, safe real/sanitized database Doctor evidence, secret review, and consistent final documentation.

Until then, retain **WAITING REAL TERMINAL ACCEPTANCE**. Do not infer GO from PR #2 being merged or Draft PR #4 CI being green.
