# PaperClaw v0.06.1 Safe Session Picker Handoff

## Status

**WAITING REAL TERMINAL ACCEPTANCE**

The narrow Safe Session Picker implementation and automated validation are complete. Physical Windows Terminal interaction and a Live Provider submit after reopen remain pending. This status must not be upgraded to complete or merge-ready until those checks are performed.

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

Not verified:

- physical terminal interaction;
- Live Provider execution after reopen;
- cross-process race behavior;
- user feedback on preview clarity.

FakeModel, fixtures, headless Textual, static checks, and CI are not real terminal E2E evidence.

## Known limitations

- Historical messages are preview-only and are not reloaded into model context.
- Stale Runs with `ended_at IS NULL` are excluded; the picker does not reconcile them.
- A second process may create a Run after selection and before submit; cross-process conversation leasing is not implemented.
- There is no checkpoint replay, crash recovery, active-process reconnect, search, rename, deletion, pagination, or retention UI.
- Message preview truncation is not a general secret-classification system.
- The parent directory of `--database` must already exist.

## Exact manual acceptance

### Prepare

```powershell
git fetch origin
git switch feat/v0.06.1-safe-session-picker
python -m pip install -e ".[dev,tui]"
$env:PAPERCLAW_API_KEY = "<real key>"
$env:PAPERCLAW_BASE_URL = "<provider base URL>"
$env:PAPERCLAW_MODEL = "<model>"
Remove-Item paperclaw.db -ErrorAction SilentlyContinue
```

### Test A — create a safely closed conversation

```powershell
paperclaw tui --workspace . --database paperclaw.db
```

Submit a small real task and wait for a terminal result, for example:

```text
创建 session_seed.txt，写入 safe-session-picker，并读取确认内容
```

Then enter `/quit`.

Expected:

- the task reaches a terminal status;
- `paperclaw.db` exists;
- the Run has a non-null `ended_at`.

### Test B — list and preview

Relaunch:

```powershell
paperclaw tui --workspace . --database paperclaw.db
```

Enter:

```text
/sessions
/preview 1
```

Expected:

- the closed conversation appears;
- preview shows recent user/assistant excerpts;
- no new Run is created merely by list or preview.

### Test C — reopen and submit a fresh Run

Enter:

```text
/open 1
```

Then submit:

```text
读取 session_seed.txt，并只报告文件中的内容
```

Expected:

- the preview remains visible after open;
- the UI states that the next submit creates a new Run;
- the task completes through the real Provider;
- the new Run has a different `run_id` but the same `conversation_id` as the original;
- the original Run remains ended with its prior stop reason.

### Test D — inspect persisted rows

After quitting, run:

```powershell
python -c "import sqlite3; c=sqlite3.connect('paperclaw.db'); print(c.execute('select conversation_id, run_id, ended_at, stop_reason from runs order by created_at, run_id').fetchall())"
```

Expected:

- at least two rows share one `conversation_id`;
- their `run_id` values differ;
- both rows have non-null `ended_at`;
- the first row was not rewritten by the second submit.

### Test E — fallback remains side-effect free

```powershell
Remove-Item fallback-should-not-exist.db -ErrorAction SilentlyContinue
paperclaw tui "直接结束并输出 fallback-ok" --no-tui --database fallback-should-not-exist.db --workspace .
Test-Path fallback-should-not-exist.db
```

Expected:

- standard CLI fallback runs;
- final `Test-Path` prints `False`.

## Evidence to return

Return after secret redaction:

- Windows and terminal versions;
- Python and Textual versions;
- one screenshot containing `/sessions` output;
- one screenshot containing `/preview` and `/open` output;
- final RunResult or sanitized terminal log for the post-open Live Provider task;
- output of the persisted-row query;
- fallback command output and `Test-Path` result;
- any traceback or corrupted-screen capture.

## Pass/fail rule

PASS only when Tests A–E succeed and the evidence contains no secret. Keep the branch and PR in `WAITING REAL TERMINAL ACCEPTANCE` / Draft state otherwise.

## Next developer steps

1. Run Tests A–E on a physical Windows Terminal with a real Provider.
2. Commit sanitized evidence under `artifacts/v0_06_1/real_acceptance/`.
3. Update this Handoff and SOP with exact versions and results.
4. Review the evidence before changing the status.
5. Do not merge automatically and do not mark the Draft PR ready without that review.
