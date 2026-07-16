# v0.09 MCP Runtime Integration — Test Report

## Status

`IMPLEMENTED / CI_PENDING / PREREQUISITE_MERGES_PENDING`

## Added automated coverage

### Unit

- MCP Tool registration alongside local Tools;
- invocation schema rejection before remote call;
- default-deny Permission;
- Permission recheck and runtime revocation;
- timeout closes only the MCP connection;
- cooperative cancellation through `ToolControlFlow`;
- redact-before-truncate ordering;
- Server discovery failure leaves local Registry usable.

### Integration

- real deterministic local stdio Fake MCP Server connect/initialize/discover/call/close;
- registered echo/add Tools execute through existing `safe_execute` path;
- local Tool remains available in the same Registry;
- `AgentRuntimeExecutor` applies existing `max_tool_calls` to MCP Tools;
- MCP Tool lifecycle persists in the existing SQLite `session_events` fact source;
- configured Server secret does not appear in durable event JSON.

## Verification commands

```powershell
python -m pytest tests/unit/test_mcp_protocol_foundation.py tests/unit/test_mcp_runtime_integration.py tests/integration/test_mcp_runtime_executor.py -q --basetemp=tmp/pytest
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

GitHub Actions on the Draft PR is the repository-wide Windows/Python 3.12 source of truth. Exact counts and artifact digest will be added after the final branch HEAD passes.

## Test classification

All tests are offline. One integration test launches the deterministic repository Fake MCP Server through real stdio pipes. No production or third-party MCP Server is contacted.
