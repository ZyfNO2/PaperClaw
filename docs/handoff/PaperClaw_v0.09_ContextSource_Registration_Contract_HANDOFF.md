# PaperClaw v0.09 Shared ContextSource Registration — Handoff

## Status

- branch: `feat/v0.09-context-source-registration-contract`;
- implementation: complete;
- repository CI: pending;
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
```

## Downstream contract

PR 5 and PR 6 should depend on this slice rather than each independently adding Executor constructor parameters or direct Prompt injection. Each adapter registers one Source and returns only `ContextCandidate` values.

## Verification

Tests are committed for descriptor determinism, freeze behavior, disabled sources, error isolation, collision handling, Executor DI, trust-separated rendering, Trace fingerprinting, and constructor conflict handling. Exact full-suite evidence will be added after GitHub Actions returns a final result.
