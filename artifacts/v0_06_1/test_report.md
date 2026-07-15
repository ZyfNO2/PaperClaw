# PaperClaw v0.06.1 Safe Session Picker Test Report

## Status

**AUTOMATED VALIDATION PASS — REAL TERMINAL / LIVE PROVIDER PENDING**

Validated implementation commit: `d912847a267be65a5a40da258d0e95c51446757c`

GitHub Actions run: `29417208949`

## Automated results

| Check | Environment | Result |
|---|---|---|
| Full pytest, excluding `real_llm` | Windows Server 2025, Python 3.12 | 388 passed, 0 failed, 0 skipped |
| Ruff high-signal gate | Ubuntu, Python 3.12 | PASS |
| Report-log session exit | pytest reportlog | exitstatus 0 |
| Headless Textual command flow | pytest | PASS |
| TUI architecture boundary | AST import gate | PASS |

Ruff command used by CI:

```text
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

Pytest command used by CI:

```text
python -m pytest --basetemp=tmp/pytest --report-log=tmp/pytest_reportlog.jsonl -q -m "not real_llm"
```

The uploaded report-log contained 388 unique call-phase test reports, all passed.

## Scope-specific evidence

The new deterministic tests verify:

- conversations with an active Run are excluded from the picker;
- a safely closed conversation is listed with latest-Run metadata;
- preview normalizes and truncates user-visible content;
- list, preview, and reopen selection do not create a Run;
- reopen revalidates the safe-closed predicate;
- selecting a conversation and submitting through QueryEngine creates a different fresh Run under the same `conversation_id`;
- the original ended Run remains ended with its original stop reason;
- the TUI `/sessions -> /preview -> /open` flow selects the expected conversation;
- `--no-tui` fallback does not create or open the requested database;
- files under `paperclaw.tui` do not directly import `paperclaw.context`, Repository, tools, or `sqlite3`.

## Failure found and corrected during development

An earlier CI run, `29416328374`, ended with 385 passed and 2 failed call-phase tests:

1. the fresh-Run test incorrectly assumed that two Runs created in the same timestamp bucket had a deterministic SQL ordering;
2. the first implementation placed the Session command boundary inside `paperclaw.tui`, directly importing `paperclaw.context` and violating the existing thin-client architecture gate.

Corrections:

- assertions now map Run rows by `run_id` instead of relying on timestamp ordering;
- `SessionCommandAPI` and persistent Repository assembly moved to `paperclaw.session_commands` outside the TUI package;
- TUI consumes only that application boundary.

The corrected branch passed run `29417208949`.

## Verification classification

### Verified

- deterministic SQLite eligibility and read-only selection contract;
- fresh-Run persistence semantics;
- old-Run immutability assertions;
- headless Textual command control flow;
- CLI fallback compatibility;
- full non-live regression and Ruff gate.

### Not verified

- physical Windows Terminal rendering and keyboard interaction for the new commands;
- Live Provider execution after `/open`;
- user-perceived clarity of the preview and reopen wording;
- behavior under two real concurrent PaperClaw processes sharing one database.

Headless Textual tests, FakeModel tests, SQLite fixtures, static import checks, and CI are not described as real end-to-end terminal validation.
