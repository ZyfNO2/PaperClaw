# PaperClaw v0.06.1 Safe Session Picker Handoff

## Status

**GO / ACCEPTED**

All Tests A–E (physical terminal interaction, Live Provider submit after reopen, SQLite query, and `--no-tui` fallback) were completed on 2026-07-16. The implementation and automated validation were already complete. The remaining physical/data gates are now closed.

## Repository and branch

- Repository: `ZyfNO2/PaperClaw`
- Base: `main@3804f72bbf0217c904c01dfabbcd046e3d930ca8`
- Branch: `feat/v0.06.1-safe-session-picker`
- Draft PR: `#3`
- Validated implementation commit: `d912847a267be65a5a40da258d0e95c51446757c`
- Automated acceptance documentation commit: `e9c2c83c75cf4b593a9334c8d56a6218123bea0c`
- Final documentation HEAD: the commit containing this Handoff; resolve with `git rev-parse HEAD` or the Draft PR head.

## Completed

- Added a read-only SafeSessionPicker over the existing v0.04 SQLite schema.
- Added stable list, preview, and reopen commands outside the TUI package.
- Added explicit `paperclaw tui --database <path>` persistence wiring.
- Added `/sessions`, `/preview <index|conversation_id>`, and `/open <index|conversation_id>`.
- Reopen selects a safely closed conversation; the next submit creates a fresh Run under the same `conversation_id`.
- The ended Run is not reopened, appended to, or mutated.
- Active Runs are excluded and safety is revalidated on preview/reopen.
- `--no-tui` fallback remains database-free.
- Existing in-memory TUI behavior remains when `--database` is omitted.
- Added deterministic SQLite, QueryEngine, headless Textual, fallback, and architecture-boundary tests.
- Updated the option audit, README, SOP, contract, limitations, test report, and file manifest.

## Main files

### Implementation

- `src/paperclaw/context/session_picker.py`
- `src/paperclaw/session_commands.py`
- `src/paperclaw/tui/app.py`
- `src/paperclaw/tui/runner.py`
- `src/paperclaw/cli.py`

### Tests

- `tests/unit/test_session_picker.py`
- `tests/unit/test_tui_session_picker.py`
- `tests/unit/test_tui_runner.py`
- existing `tests/unit/test_tui_architecture.py`

### Documentation and artifacts

- `Plan/PaperClaw_v0.06.1_Safe_Session_Picker_SOP.md`
- `Plan/PaperClaw_v0.03-v0.06_PostMVP_Option_Audit.md`
- `artifacts/v0_06_1/session_picker_contract.md`
- `artifacts/v0_06_1/known_limitations.md`
- `artifacts/v0_06_1/test_report.md`
- `artifacts/v0_06_1/file_manifest.txt`
- `README.md`

## Key architecture decisions

1. **Reopen a conversation, never an ended Run.** Selection is read-only. QueryEngine creates a new Run only on the next submit.
2. **Fail closed.** A conversation is selectable only when the latest Run has `ended_at` and no Run under that conversation remains active.
3. **Keep SQLite out of the TUI package.** Storage and executor assembly live in `paperclaw.session_commands`; TUI imports only the application boundary.
4. **Keep the picker read-only.** Picker connections use SQLite URI `mode=ro` and `PRAGMA query_only = ON`; they do not migrate or create a database.
5. **Use existing persistence.** New Runs continue through `AgentRuntimeExecutor -> SessionService -> SQLiteRepository`.
6. **Preview is not semantic resume.** Historical messages are shown to the user but are not automatically injected into the model prompt.
7. **Preserve optional TUI behavior.** Textual remains lazy and `--no-tui` returns through the existing CLI fallback before any database is opened.

## Tests and CI

### Green run

- GitHub Actions run: `29417208949`
- Validated SHA: `d912847a267be65a5a40da258d0e95c51446757c`
- Windows full pytest excluding `real_llm`: **388 passed, 0 failed, 0 skipped**
- Ruff high-signal gate: **PASS**
- Report-log session exitstatus: `0`

### Failure retained for traceability

Earlier run `29416328374` had **385 passed, 2 failed**:

- one new test relied on unstable ordering for Runs created in the same timestamp bucket;
- TUI directly imported `paperclaw.context.session_picker`, violating the existing architecture gate.

Both were fixed. The test now indexes rows by Run ID, and the command/persistence boundary moved to `paperclaw.session_commands`.

### Verification classification

Verified by offline automation:

- SQLite eligibility predicate;
- read-only list/preview/reopen selection;
- active-Run exclusion and revalidation;
- fresh Run under the same conversation;
- original ended Run preservation;
- headless Textual command flow;
- CLI fallback compatibility;
- TUI package import boundary;
- full non-live regression.

Verified by physical terminal acceptance (2026-07-16):

- physical terminal interaction: PASS;
- Live Provider execution after reopen: PASS;
- SQLite persistence verification: PASS;
- `--no-tui` fallback side-effect free: PASS.

## Known limitations

- Historical messages are preview-only and are not reloaded into model context.
- Stale Runs with `ended_at IS NULL` are excluded; the picker does not reconcile them.
- A second process may create a Run after selection and before submit; cross-process conversation leasing is not implemented.
- There is no checkpoint replay, crash recovery, active-process reconnect, search, rename, deletion, pagination, or retention UI.
- Message preview truncation is not a general secret-classification system.
- The parent directory of `--database` must already exist.

## Acceptance results (2026-07-16)

### Test A — create a safely closed conversation

Result: PASS. Run `run-26336a5f6cfd` created with non-null `ended_at` and `stop_reason=verification_failed`.

### Test B — list and preview

Result: PASS. `/sessions` listed conversation `tui-cd403f47a79b`; `/preview 1` showed user/assistant excerpts; no new Run created.

### Test C — reopen and submit a fresh Run

Result: PASS. `/open 1` showed "Conversation reopened safely. The next submission creates a new Run." New Run `run-3c6fe0f8e485` completed with `stop_reason=completed_verified`; same `conversation_id` as original.

### Test D — inspect persisted rows

Result: PASS. Two rows share `conversation_id=tui-cd403f47a79b` with different `run_id` values; both have non-null `ended_at`; first row not rewritten.

### Test E — fallback remains side-effect free

Result: PASS. Standard CLI fallback executed; `Test-Path fallback-should-not-exist.db` returned `False`.

## Environment

- Windows: Microsoft Windows 11, build `26200`
- Windows Terminal: `1.24.11321.0`
- Python: `3.12.8`
- Textual: `7.5.0`
- Provider: local `.env` configuration

## Pass/fail

PASS. Tests A–E succeeded. The branch and PR may proceed to Ready-for-Review and merge.
