# PaperClaw v0.28 Project Knowledge Runtime + Lifecycle — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

- Branch: `feat/v0.28-project-knowledge-runtime`
- Draft PR: `#57`
- Stack base: `feat/v0.27-forgotten-debt-product-foundation @ 95008519a612ab61e552e7099d15d792c0f17752`
- Exact validated implementation SHA: `e09678f0111e359296e18ed9881ac2fc9517a278`
- Validation run: `29661038898`

## Delivered

### Project knowledge lifecycle

- `ProjectIndexPolicy`
- `ProjectKnowledgeRuntime`
- `ProjectKnowledgeWatcher`
- explicit inspect/rebuild/refresh operations
- `require_current`, `allow_stale`, `disabled`
- `allow_stale` limited to valid fingerprint staleness
- metadata corruption and project identity mismatch remain fail-closed

### Project-scoped memory

- global USER profile remains shared
- project/environment MEMORY moves to `projects/<project_id>/MEMORY.md`
- explicit opt-out preserves legacy behavior
- Memory Tool uses the same routed store

### Hybrid retrieval seam

- backend-neutral `Retriever` protocol
- deterministic weighted reciprocal-rank fusion
- corpus mismatch rejection
- chunk/citation identity preservation
- deterministic tie breaking
- no built-in network or embedding provider

### CLI

```text
paperclaw project --workspace . refresh
paperclaw project --workspace . watch --once
paperclaw project --workspace . watch --once --rebuild-on-change
```

No watcher starts implicitly with normal Agent execution.

## Validation

```text
implementation SHA: e09678f0111e359296e18ed9881ac2fc9517a278
run: 29661038898
918 passed / 0 failed
10 marker-driven setup skips
artifact: v028-full-regression-29661038898
digest: sha256:f4a4062531f0e14315c6999f2cc8f3271bcef6d06ab24ab7db01fccf7bed1769
```

Linux and Windows focused gates, compatibility slices, full Windows non-live regression and Ruff all passed.

## Limits

- semantic/vector backend is an adapter seam, not a hosted implementation;
- watcher is polling and explicit;
- no background daemon or external vector DB;
- `allow_stale` does not permit broken metadata;
- project USER isolation is intentionally not enabled; user profile remains global.

## Next stacked line

`feat/v0.29-artifact-revisions` / Draft PR #58.

## Final classification

**COMPLETE**

PR remains Draft and unmerged.
