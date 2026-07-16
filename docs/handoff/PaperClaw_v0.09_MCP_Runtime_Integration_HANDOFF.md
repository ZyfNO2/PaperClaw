# PaperClaw v0.09 MCP Runtime Integration — Handoff

## 1. Status

- Repository: `ZyfNO2/PaperClaw`
- Branch: `feat/v0.09-mcp-runtime-integration`
- Status: `IMPLEMENTED / CI_PENDING / STACKED_PR`
- Base used for development: MCP Protocol Foundation head `bb5efe746d159a1ce9e33466649b141f4fa8d7ee`
- Required before merge: v0.08 PR #19 and MCP Protocol Foundation PR #21 must be accepted into the target branch
- Capability selection: intentionally not implemented

This branch must not be represented as directly main-ready while either prerequisite remains unmerged.

## 2. Completed

- Added `MCPRuntimeTool` as an adapter to the existing Tool contract.
- Added stable `mcp.<server>.<tool>` ToolRegistry names.
- Added atomic discovery/registration with collision preflight.
- Added invocation-time validation for the normalized JSON Schema subset.
- Added default-deny and explicit allowlist Permission policies.
- Rechecks Permission immediately before every session call.
- Added bounded timeout and cooperative cancellation behavior.
- Reuses existing AgentRuntime `max_tool_calls` with no second budget implementation.
- Reuses existing Tool events and SQLite `session_events` Trace path.
- Redacts remote output/error before applying the Tool output limit.
- Converts remote failures into structured Tool failures without crashing local Runtime.
- Preserves existing local Tool operation when Server registration or invocation fails.
- Added deterministic unit, local stdio and Runtime/Trace integration coverage.

## 3. Main files

### Runtime

- `src/paperclaw/mcp/validation.py`
- `src/paperclaw/mcp/runtime.py`
- `src/paperclaw/mcp/__init__.py`

### Tests

- `tests/unit/test_mcp_runtime_integration.py`
- `tests/integration/test_mcp_runtime_executor.py`

### Documents

- `Plan/PaperClaw_v0.09_MCP_Runtime_Integration_SOP.md`
- `artifacts/v0_09_runtime/implementation_summary.md`
- `artifacts/v0_09_runtime/test_report.md`
- `artifacts/v0_09_runtime/known_limitations.md`
- `docs/handoff/PaperClaw_v0.09_MCP_Runtime_Integration_HANDOFF.md`

## 4. Architecture decisions

1. MCP does not receive a separate Runtime, QueryEngine, Budget or Trace database.
2. Registration is explicit and atomic; no capability selection occurs.
3. Remote Tool descriptions remain marked as untrusted data.
4. Default Permission is deny; discovery does not imply execution permission.
5. Permission is evaluated with current arguments and `ToolContext` at invocation time.
6. Timeout/cancel closes the single-flight connection to prevent late response reuse.
7. Environment values are used only as exact redaction inputs and are excluded from metadata.
8. Server failure is isolated as registration data or a `ToolResult`; existing local Registry entries remain usable.

## 5. Verification

Pending final GitHub Actions results.

Recommended commands:

```powershell
python -m pytest tests/unit/test_mcp_protocol_foundation.py tests/unit/test_mcp_runtime_integration.py tests/integration/test_mcp_runtime_executor.py -q --basetemp=tmp/pytest
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## 6. Not verified / not implemented

- No third-party MCP Server interoperability test.
- No real production remote Tool or remote write operation.
- No capability selection, routing, reconnect, Resources, Prompts or approval UI.
- No automatic merge or main branch mutation.

## 7. Next developer steps

1. Resolve any CI findings on this branch.
2. Merge/accept v0.08 and MCP Protocol Foundation in dependency order.
3. Update this branch onto the accepted target branch and rerun full CI.
4. Review the final diff to ensure Protocol Foundation files are no longer duplicated by the stack.
5. Keep capability selection in a separate later PR.
