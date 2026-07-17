# PaperClaw v0.09 MCP Capability Selection — Handoff

## Status

- branch: `feat/v0.09-mcp-capability-selection`;
- stacked base: MCP Runtime PR #23;
- additional dependency: Shared ContextSource Registry PR #25;
- implementation: complete;
- repository CI: pending;
- merge: not requested and not performed.

## Delivered

- `MCPCapabilityMetadata`;
- `MCPCapabilityIndex` and frozen snapshot;
- selection-time Permission policy;
- deterministic task/keyword/scope/permission Top-K;
- `MCPCapabilityContextSource`;
- runtime binding helper through the shared Registry;
- remote description isolation from the base Tool surface;
- selection metrics and fixture;
- complete offline MCP MVP E2E.

## Invariants

1. Discovery metadata is indexed; Server instructions are never indexed.
2. Selection Permission is visibility eligibility only.
3. Invocation Schema validation and Permission recheck remain authoritative.
4. Remote description enters Context only as `external_untrusted` data.
5. MCP selection code does not import or invoke PromptAssembler.
6. ContextOrchestrator owns budget, trust separation and final Prompt rendering.
7. Top-K order is deterministic.
8. A frozen capability index is immutable for one Runtime.
9. Local Tool and MCP Runtime behavior from PR #23 remain unchanged except description containment.

## Main files

```text
src/paperclaw/mcp/selection.py
src/paperclaw/mcp/selection_runtime.py
src/paperclaw/mcp/selection_evaluation.py
src/paperclaw/mcp/__init__.py

tests/unit/test_mcp_capability_selection.py
tests/integration/test_mcp_capability_selection_e2e.py
tests/fixtures/mcp_tool_selection_fixture.json
```

## Dependency handling

The PR must remain Draft while PR #23 and PR #25 are unmerged. After both merge, rebase this branch onto `main`, remove duplicated dependency commits from the diff, rerun full CI, then consider Ready for Review.

## Verification

Automated tests and artifacts are committed. Exact GitHub Actions evidence remains pending because the connector currently returns upstream 502 for workflow status endpoints. No Repository GO claim is made until a final branch HEAD run succeeds.
