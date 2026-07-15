# PaperClaw v0.06 TUI MVP Handoff

## Status

**WAITING REAL TERMINAL ACCEPTANCE**

PR #2 has been merged into `main`, but merge state is not acceptance GO. The implementation, automated Windows regression, Ruff checks, SQLite fixture Doctor smoke, live-provider backend path, physical wide-terminal launch/task and Verification Inspector rendering have evidence. The following gates remain open:

- physical Windows Terminal width below 80 columns;
- post-fix physical TUI `/cancel` capture;
- Doctor quick/full checks against a safe real or sanitized database copy;
- final evidence review.

## Repository state

- Repository: `ZyfNO2/PaperClaw`
- Current base: `main`
- PR #2: merged on 2026-07-15
- PR #2 source HEAD: `d5d43e3cd74e80d35190e16253446f37841a4b2e`
- Main integration commit: `3804f72bbf0217c904c01dfabbcd046e3d930ca8`
- Repair branch: `fix/v0.06-acceptance-cancel-race`
- Repair PR: Draft PR #4

The historical source branch `feat/v0.06-tui-mvp` is no longer the acceptance authority. Use `main` plus Draft PR #4 for the current code review state.

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

Cancellation remains cooperative. It does not forcibly interrupt a synchronous provider call, shell process or process tree.

Only adapter calls already in flight may translate a post-stop exception into cooperative control flow:

- provider `complete()`;
- Tool `validate()` for non-validation runtime exceptions;
- Tool `execute()` after the repair in PR #4.

The original sanitized failure event is emitted before translation. Unrelated runtime, session and persistence exceptions remain `runtime_failed`, even when a stop token was accepted concurrently.

## Evidence matrix

| Gate | Status | Code provenance | Evidence / boundary |
|---|---|---|---|
| Original final source-head Windows CI | PASS | `d5d43e3...` | run `29413807619` / #45; 382 call-phase tests passed; Ruff passed |
| Repair PR Windows CI | PENDING | Draft PR #4 HEAD | must pass before review completion |
| Provider exception-after-stop race | PASS | `d5d43e3...` | deterministic adapter unit test |
| Tool `execute()` exception-after-stop race | PENDING CI | Draft PR #4 | deterministic blocking Tool fixture added |
| Windows Terminal wide launch | PASS | screenshot record reports `0ef5b0b...` | `artifacts/v0_06/real_acceptance/windows_terminal_wide.png` |
| Physical live create/run/verify task | PASS with historical provenance | original acceptance record | screenshot/report; does not prove post-repair cancel |
| Verification Inspector readability | PASS with historical provenance | original acceptance record | aggregate visible; raw observed output not shown |
| Windows Terminal narrow resize | PENDING MANUAL | — | physical screenshot below 80 columns required |
| Physical post-fix TUI `/cancel` | PENDING MANUAL | — | original screenshot ended `runtime_failed`; fixed path requires recapture |
| SQLite migrated-fixture Doctor | PASS (smoke only) | original acceptance record | quick/full returned `ok`; not a user database gate |
| Safe real/sanitized DB Doctor | PENDING MANUAL | — | quick/full JSON required |

## Automated commands

```powershell
python -m pip install -e ".[dev,tui]"
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

Focused repair test:

```powershell
python -m pytest tests/unit/test_agent_runtime_executor.py -q
```

## Remaining physical acceptance

### A. Narrow resize

```powershell
paperclaw tui --workspace .
```

Resize below 80 columns and confirm:

- Chat and Timeline stack vertically;
- input remains usable;
- no crash or corrupted screen;
- capture a sanitized screenshot showing the terminal width.

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

A successful backend test does not replace this physical TUI capture.

### C. Safe database Doctor

Run only against a non-unique copy or sanitized database:

```powershell
paperclaw doctor --database path\to\copy.db
paperclaw doctor --database path\to\copy.db --full
```

Return redacted JSON. Do not run automatic repair or migration as part of this gate.

## Acceptance decision

`GO` requires all of the following:

- repair PR CI passes;
- narrow physical resize passes;
- post-fix physical TUI `/cancel` passes;
- safe real/sanitized database Doctor passes or is explicitly removed from the release claim;
- evidence contains no secret;
- Handoff, SOP and test report identify the same commit and gate status.

Until then, retain **WAITING REAL TERMINAL ACCEPTANCE**. Do not infer GO from PR #2 being merged.
