# PaperClaw v0.15 Test Report

## Exact validated code head

`14362a91dc65899e321ed70da3e3b7de0c8c0e86`

## Full non-live regression

- Workflow: `CI`
- Run ID: `29617801928`
- Platform: GitHub Actions Windows runner, Python 3.12
- Result: **717 passed, 0 failed**
- Ruff correctness gate: **PASS**
- Pytest artifact: `pytest-results-29617801928`
- Artifact ID: `8421160991`
- Artifact digest: `sha256:c435b3b5940ddf25933797f1d8665dc4f265858356ad1169afdc15c8e668f9e8`

The test count was read from the uploaded pytest report log's call-phase records; setup and teardown records are not counted as tests.

## Desktop compatibility and packaging

- Workflow: `Desktop package smoke`
- Run ID: `29617801933`
- Desktop focused tests: **PASS**
- Windows PyInstaller `onedir`: **PASS**
- Executable and packaged HTML/CSS/JS verification: **PASS**
- Package artifact: `PaperClaw-Windows-onedir-29617801933`
- Package artifact ID: `8421129998`
- Package digest: `sha256:8c1babe46953bc5ab77b2a363013769a438ca22b581adf45a8c97fc2e9c3dc17`
- Focused test artifact: `desktop-pytest-results-29617801933`
- Focused test artifact ID: `8421123816`
- Focused test digest: `sha256:e0eb9fc460bf33b52b91023bf2252a76feece82cd3f2c7fe612b4ccaf876ffbc`

## v0.15 focused coverage

- durable API execution from queued state to terminal result;
- idempotency after service recreation;
- persisted public-event replay and sequence resume;
- cancellation during active execution;
- cancellation before runtime run-ID publication;
- queue-timeout error classification;
- cross-Python-process expired-lease reconciliation;
- event replay from a database written by a previous process;
- workspace path-traversal denial;
- loopback/private/link-local/metadata URL denial;
- destructive tool approval requirement;
- authorization policy exception and invalid-result fail-closed behavior.

## Evidence classification

These results prove deterministic offline control flow, SQLite persistence, cross-process reconciliation, policy enforcement and repository regression. They do not constitute a real external Provider/Uvicorn acceptance test or proof of distributed execution semantics.
