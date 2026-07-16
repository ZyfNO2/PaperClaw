# v0.09 MCP Runtime Integration — Implementation Summary

## Delivered

- `MCPRuntimeTool` adapter implementing the existing PaperClaw Tool contract;
- deterministic node-safe MCP Tool names compatible with the existing `NodeRegistry`;
- atomic discovery/registration into the existing `ToolRegistry` with collision preflight;
- fail-closed invocation-time JSON Schema validation;
- default-deny Permission policy and explicit allowlist policy;
- Permission recheck immediately before every remote invocation;
- bounded timeout and cooperative cancellation handling;
- reuse of existing AgentRuntime `max_tool_calls` budget;
- reuse of existing Tool lifecycle events and SQLite `session_events` Trace;
- remote output/error redaction before Tool output truncation;
- structured MCP failures that do not crash the local Runtime;
- local Tool survival when MCP connect/discovery/call fails;
- deterministic unit tests, real local stdio Fake Server integration, and Runtime/Trace integration tests.

## Architecture decisions

1. No MCP-specific Agent, QueryEngine, Budget or Trace path was introduced.
2. Registration is explicit; capability selection remains out of scope.
3. Registry names use readable slugs plus a 12-character SHA-256 identity suffix, while Permission continues to use exact `server_id.tool_name` identity.
4. Registration failure is returned as `MCPRegistrationResult`, leaving existing local Tools unchanged.
5. Permission defaults to deny and is evaluated at execution time, not cached at discovery time.
6. Synchronous protocol calls run behind a cancellation-aware daemon worker because the merged protocol session is single-flight and synchronous.
7. Timeout/cancellation closes the connection to prevent late responses from contaminating subsequent requests.
8. Environment values used to launch a Server become exact redaction inputs but never enter durable metadata.
9. Existing Trace records MCP lifecycle through the normal Tool events; no parallel MCP TraceStore or event taxonomy was added.

## Main files

- `src/paperclaw/mcp/validation.py`
- `src/paperclaw/mcp/runtime.py`
- `src/paperclaw/mcp/registration.py`
- `src/paperclaw/mcp/__init__.py`
- `tests/unit/test_mcp_runtime_integration.py`
- `tests/integration/test_mcp_runtime_executor.py`
- `tests/property/test_trace_properties.py`（test-generator collision fix）

## Validation

- Final code validation HEAD: `013fffd519e86efa88ef6e9d8e178a95224097de`
- GitHub Actions run: `29517520350`
- Windows pytest: `571 passed, 0 failed, 0 skipped`
- Ruff high-signal gate: PASS
- Artifact digest: `sha256:83728a4cb5e7f26f657afd88c427954f3e4a11deee9326dedc75c510685a20b0`

The pytest reportlog contains 571 setup, 571 call and 571 teardown success records. Only the 571 call records are test-case outcomes; 1713 is not the test count.

## Explicit non-goals

- capability selection or automatic routing;
- ContextOrchestrator/Prompt injection;
- Resources/Prompts;
- reconnect or capability refresh;
- Human approval UI;
- remote write retry/idempotency;
- third-party production MCP Server interoperability.
