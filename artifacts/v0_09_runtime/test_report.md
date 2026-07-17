# v0.09 MCP Runtime Integration — Test Report

## Status

`COMPLETE / OFFLINE_GO / CI_PASS`

## Added automated coverage

### Unit

- MCP Tool registration alongside local Tools;
- node-safe deterministic Tool identity;
- invocation schema rejection before remote call;
- default-deny Permission;
- Permission recheck and runtime revocation;
- timeout closes only the MCP connection;
- cooperative cancellation through `ToolControlFlow`;
- redact-before-truncate ordering;
- Server discovery failure leaves local Registry usable.

### Integration

- real deterministic local stdio Fake MCP Server connect/initialize/discover/call/close;
- registered echo/add Tools execute through the existing `safe_execute` path;
- local Tool remains available in the same Registry;
- `AgentRuntimeExecutor` applies existing `max_tool_calls` to MCP Tools;
- MCP Tool lifecycle persists in the existing SQLite `session_events` fact source;
- configured Server secret does not appear in durable event JSON.

### Existing regression repaired

Initial run `29516623795` produced 569 passing and 2 failing test cases:

1. dotted MCP action names produced invalid `tool:<name>` NodeRegistry IDs; fixed by node-safe slugs plus an exact-identity hash;
2. an existing Hypothesis redaction property generated `secret="authoriz"`, which appeared in the fixed JSON key `authorization` after values were correctly redacted; fixed by generating explicitly prefixed Secret values so the assertion measures payload content rather than schema keys.

## Final code verification

- Code validation HEAD: `013fffd519e86efa88ef6e9d8e178a95224097de`
- GitHub Actions run: `29517520350`
- Windows Server 2025 / Python 3.12 pytest: `571 passed`
- Failed: `0`
- Skipped: `0`
- pytest exit status: `0`
- Ruff E9/F63/F7/F82: PASS
- Artifact: `pytest-results-29517520350`
- Artifact digest: `sha256:83728a4cb5e7f26f657afd88c427954f3e4a11deee9326dedc75c510685a20b0`

## Final documentation-head verification

- Documentation closeout HEAD: `02b4c3a95e308917e86fa6d6032e7f9422b0d857`
- GitHub Actions run: `29518130494`
- Windows pytest: `571 passed, 0 failed, 0 skipped`
- Ruff: PASS
- Artifact digest: `sha256:da41bfb72bdaa04feda6a367e767606ac9a9435edf89457b96bafcdcb6580c20`

## Count methodology

`pytest-reportlog` writes a TestReport for setup, call and teardown. The final artifact contains:

```text
setup passed: 571
call passed: 571
teardown passed: 571
SessionFinish exitstatus: 0
```

The authoritative test-case count is therefore **571 passed**, not 1713. The latter is only the sum of three lifecycle records per test.

## Verification commands

```powershell
python -m pytest tests/unit/test_mcp_protocol_foundation.py tests/unit/test_mcp_runtime_integration.py tests/integration/test_mcp_runtime_executor.py -q --basetemp=tmp/pytest
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## Test classification

All tests are offline. One integration test launches the deterministic repository Fake MCP Server through real stdio pipes. No production or third-party MCP Server is contacted, so real interoperability remains not verified and is not represented as completed.
