# PaperClaw v0.09 MCP Runtime Integration — Handoff

## 1. Status

- Repository: `ZyfNO2/PaperClaw`
- Branch: `feat/v0.09-mcp-runtime-integration`
- Draft PR: `#23`
- Status: `COMPLETE / OFFLINE_GO / CI_PASS / NOT_MERGED`
- Base: `main@872c4532fe00b3a3e8b72202fdd4c504594d8acc`
- Final validated implementation HEAD: `013fffd519e86efa88ef6e9d8e178a95224097de`
- Prerequisites: v0.08 PR #19 and MCP Protocol Foundation PR #21 are merged
- Capability selection: intentionally not implemented

The branch may contain a later documentation-only closeout commit. The validated implementation SHA and CI evidence above remain the executable acceptance point; the current branch HEAD is recorded in PR #23 and the final development report.

## 2. Completed

- Added `MCPRuntimeTool` as an adapter to the existing Tool contract.
- Added stable, node-safe MCP ToolRegistry identities with exact-identity collision hashes.
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
- Repaired an existing Hypothesis redaction property that could confuse generated Secret content with fixed JSON field names.

## 3. Main files

### Runtime

- `src/paperclaw/mcp/validation.py`
- `src/paperclaw/mcp/runtime.py`
- `src/paperclaw/mcp/registration.py`
- `src/paperclaw/mcp/__init__.py`

### Tests

- `tests/unit/test_mcp_runtime_integration.py`
- `tests/integration/test_mcp_runtime_executor.py`
- `tests/property/test_trace_properties.py`

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
4. Registry names satisfy the existing NodeRegistry character contract and include a hash of the exact remote identity.
5. Permission identity remains exact `server_id.tool_name`; Registry slugging never changes authorization identity.
6. Default Permission is deny; discovery does not imply execution permission.
7. Permission is evaluated with current arguments and `ToolContext` at invocation time.
8. Timeout/cancel closes the single-flight connection to prevent late response reuse.
9. Environment values are used only as exact redaction inputs and are excluded from metadata.
10. Server failure is isolated as registration data or a `ToolResult`; existing local Registry entries remain usable.

## 5. Test and CI evidence

- Initial diagnostic run: `29516623795` — failed with two identified and fixed issues.
- Final passing run: `29517520350`.
- Windows pytest: `1713 passed, 0 failed, 0 skipped`.
- pytest exit status: `0`.
- Ruff E9/F63/F7/F82: PASS.
- Artifact: `pytest-results-29517520350`.
- Artifact digest: `sha256:83728a4cb5e7f26f657afd88c427954f3e4a11deee9326dedc75c510685a20b0`.

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
- Generic Trace stores MCP invocation through the normal Tool lifecycle and node-safe Tool identity; no MCP-specific event schema was introduced.
- No automatic merge or main branch mutation.

## 7. Next developer steps

1. Review Draft PR #23 against this Handoff and CI artifact.
2. Keep capability selection in a separate later PR.
3. When capability selection is implemented, consume exact descriptor identity and never infer permission from the node-safe Registry name.
4. Add third-party interoperability only when a concrete Server/user story exists; do not convert local Fake Server results into a production claim.
