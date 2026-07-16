# v0.09.1 BM25 / Incremental Retrieval — Test Report

## Status

`IMPLEMENTATION_COMPLETE / REPOSITORY_CI_PENDING`

## Static and local smoke evidence

A standalone SQLite FTS5 smoke executed the same scoped query shape used by `SQLiteBM25Retriever`:

```sql
WHERE chunk_fts MATCH ? AND document_id IN (?)
ORDER BY bm25(...), chunk_id, rowid
LIMIT ?
```

Result:

- statement executed successfully;
- scope was applied before pool limit;
- `total_matches = 1`;
- the requested target document was returned.

This smoke validates SQLite/FTS syntax only. It is not a substitute for repository pytest.

## Automated test coverage added

- deterministic request identity and bounds;
- incremental add/noop/update/delete;
- old token stale invalidation after update/delete;
- pinned Manifest mismatch;
- duplicate content filtering;
- fake stale FTS row filtering;
- heading drift filtering;
- document scope before candidate-pool limit;
- legal broken Manifest state;
- tampered ready Manifest contract;
- missing/stale FTS inspection and rebuild;
- manifest identity/content collision during rebuild;
- metric definitions;
- fixed retrieval fixture quality Gate.

## Offline retrieval fixture target

```text
Recall@3 = 1.0
MRR      = 1.0
nDCG@3   = 1.0
```

These values are assertions in the deterministic fixture test. They will be reported as verified only after repository CI succeeds.

## Repository CI

GitHub Actions run ID, final test-case count, failure count, skipped count, Ruff result, and artifact digest are pending because the GitHub connector currently returns an upstream 502 for Actions/PR status endpoints.

No Repository GO claim is made while this section is pending.
