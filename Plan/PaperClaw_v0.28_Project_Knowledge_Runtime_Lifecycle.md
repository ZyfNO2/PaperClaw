# PaperClaw v0.28 Project Knowledge Runtime + Lifecycle

> Status: implementation complete / acceptance complete
> Stack base: `feat/v0.27-forgotten-debt-product-foundation @ 95008519a612ab61e552e7099d15d792c0f17752`
> Branch: `feat/v0.28-project-knowledge-runtime`
> Draft PR: `#57`
> Validated implementation SHA: `e09678f0111e359296e18ed9881ac2fc9517a278`

## Goal

Turn the v0.27 project manifest and deterministic local index into a complete runtime lifecycle without silently trusting stale knowledge.

## Delivered

- explicit index policy: `require_current`, `allow_stale`, `disabled`;
- `allow_stale` accepts only a structurally valid `index_stale`, never corrupt metadata or project-ID mismatch;
- project-scoped memory namespace derived from `project_id`;
- global USER profile retained while project MEMORY is isolated;
- project knowledge lifecycle service with inspect/rebuild/refresh operations;
- bounded polling watcher with explicit start/stop and no implicit background thread;
- backend-neutral Retriever protocol;
- deterministic weighted reciprocal-rank fusion;
- corpus-hash mismatch rejection;
- chunk identity, locator and content hash preserved through fusion;
- CLI `project refresh` and explicit one-shot `project watch --once`;
- existing non-project workspaces remain backward compatible.

## Runtime model

```text
global memory root
  ├─ USER.md
  └─ projects/<project_id>/MEMORY.md

ProjectKnowledgeRuntime
  ├─ require_current -> current index only
  ├─ allow_stale -> valid stale fingerprint only
  └─ disabled -> no retriever/rebuild

HybridRetriever
  ├─ lexical backend
  ├─ optional semantic backend
  └─ deterministic weighted RRF
```

## Safety boundaries

- no hosted embedding provider;
- no hidden network calls;
- no mandatory filesystem watcher;
- watcher failures do not mutate the active Agent runtime;
- no corrupt metadata accepted through `allow_stale`;
- no external vector database claim;
- no automatic merge.

## Validation

Exact implementation SHA:

```text
e09678f0111e359296e18ed9881ac2fc9517a278
```

GitHub Actions run:

```text
29661038898
```

Results:

- Ubuntu focused: SUCCESS
- Windows focused: SUCCESS
- Context / Memory / Retrieval compatibility: SUCCESS on both platforms
- full Windows non-live regression: SUCCESS
- Ruff: SUCCESS

Machine-readable regression:

```text
918 passed / 0 failed
10 marker-driven setup skips
artifact: v028-full-regression-29661038898
digest: sha256:f4a4062531f0e14315c6999f2cc8f3271bcef6d06ab24ab7db01fccf7bed1769
```

## Follow-on

```text
v0.29 Artifact Revisions
  -> immutable numbered revisions
  -> content-addressed blobs
  -> Run/Task/Trace/Project source links
  -> safe export

v0.30 Desktop Product Integration
  -> capabilities
  -> projects
  -> artifacts
  -> read-only operational status
```

## Final classification

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

PR #57 remains Draft and unmerged.
