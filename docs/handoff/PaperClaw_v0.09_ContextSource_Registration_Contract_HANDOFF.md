# PaperClaw v0.09 Shared ContextSource Registration — Handoff

## Status

- branch: `feat/v0.09-context-source-registration-contract`;
- Draft PR: `#25`;
- implementation: complete;
- repository CI: PASS;
- status: `OFFLINE_GO`;
- merge: not requested and not performed.

## Public surface

```text
paperclaw.context.ContextSourceRegistry
paperclaw.context.ContextSourceDescriptor
paperclaw.context.ContextSourceRegistrySnapshot
paperclaw.context.ContextSourceCollectionError
paperclaw.context.ContextSourceRegistryFrozen
```

`ContextOrchestratedAgentRuntimeExecutor` accepts an optional `context_source_registry`. It freezes the Registry, captures a stable snapshot, and supplies the Registry to the existing `ContextOrchestrator` as one composite source.

## Invariants

1. Source registration is deterministic and immutable after Runtime construction.
2. Duplicate source IDs and candidate IDs fail closed.
3. Source collection errors identify the Source without replaying raw exception text.
4. Disabled sources are not invoked.
5. Registry metadata fingerprint is content-free and durable-Trace safe.
6. Candidate trust, scope, priority, bucket, and content remain owned by the Source contract and ContextOrchestrator policy.
7. Only PromptAssembler renders Provider input.
8. QueryEngine, ToolRegistry, Permission, Retrieval, and MCP execution paths are unchanged.

## Main files

```text
src/paperclaw/context/source_registry.py
src/paperclaw/context/__init__.py
src/paperclaw/harness/context_runtime_executor.py
tests/unit/test_context_source_registry.py
Plan/PaperClaw_v0.09_ContextSource_Registration_Contract.md
artifacts/v0_09_context_source/test_report.md
```

## Verification

Validated branch HEAD before documentation closeout:

```text
b3625c9f0e6d851fb81b09a7444aa91cb0fd26dd
```

```text
GitHub Actions run: 29541766937
Windows pytest: 567 passed, 0 failed, 0 skipped
pytest exit status: 0
Ruff E9/F63/F7/F82: PASS
artifact: pytest-results-29541766937
artifact digest: sha256:0621460b94791cba0aca7b89c05c1298f76bdff0de2efc9e5a081d0668524aed
```

The test count uses call-phase report records only.

## Downstream contract

PR #26 and PR #27 depend on this slice rather than each independently adding Executor constructor parameters or direct Prompt injection. Each adapter registers one Source and returns only `ContextCandidate` values.

Both downstream PRs remain Draft and explicitly stacked until this shared contract and their domain-specific prerequisites merge.
