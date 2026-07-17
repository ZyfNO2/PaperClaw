# v0.09.1 BM25 / Incremental Retrieval — Test Report

## Status

`IMPLEMENTATION_COMPLETE / REPOSITORY_CI_PASS / OFFLINE_GO`

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

## Automated coverage

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
- Manifest identity/content collision during rebuild;
- metric definitions;
- fixed retrieval fixture quality Gate.

## Offline retrieval fixture

The deterministic four-query fixture passed:

```text
Recall@3 = 1.0
MRR      = 1.0
nDCG@3   = 1.0
```

This fixture is a regression Gate, not a public retrieval benchmark.

## Repository CI

Validated branch HEAD:

```text
3442a60615a92ea360c0ef1544a06d19b6dba1a0
```

GitHub Actions:

```text
run: 29541314820
runner: Windows Server 2025
pytest call-phase: 572 passed, 0 failed, 0 skipped
pytest exit status: 0
Ruff E9/F63/F7/F82: PASS
artifact: pytest-results-29541314820
artifact digest: sha256:f757df67df136d1e269118f53aafcad832b28b5e3e9ad0ff0060660555915ce7
```

The test-case count is derived only from `when == "call"` records in `pytest_reportlog.jsonl`; setup and teardown lifecycle records are not counted as additional tests.

## Post-acceptance repair validation (2026-07-17)

Manual D1–D5 acceptance exposed two defects: returning to a historical corpus
left the wrong Manifest at the read head, and natural Chinese questions had no
usable lexical candidate path. The repaired Gate adds explicit regressions for:

- historical Manifest reactivation, including a legacy
  `UNIQUE(content_hash)` index;
- retained-document retrieval and deleted-document absence after reactivation;
- Chinese natural-query recall when the keyword is not at the FTS token prefix;
- abstention for a lexically similar but unsupported Chinese question;
- existing English prefix retrieval.

Final local evidence:

```text
targeted repair suite: 18 passed
full non-live suite:   640 passed, 1 skipped, 4 deselected
Ruff E9/F63/F7/F82:    PASS
manual D1-D5 script:   PASS
```

The single skip is the Windows symlink privilege case and is unrelated to RAG.
