# v0.09.1 BM25 / Incremental Retrieval — Implementation Summary

## Delivered

- frozen `RetrievalRequest`, `RetrievalCandidate`, and `RankedResult` contracts;
- deterministic SQLite FTS5 BM25 read-side;
- request-level Manifest/corpus snapshot pinning;
- scope filtering before candidate-pool truncation;
- exact active Chunk/Version/Document and FTS payload validation;
- stale row and exact duplicate filtering;
- incremental add/update/delete/unchanged-noop orchestration;
- projected active Manifest generation;
- reuse of the existing atomic `SQLiteDocumentRegistry` mutation path;
- exact index integrity inspection;
- broken FTS and Manifest rebuild from active immutable Chunks;
- deterministic retrieval fixture;
- Recall@K, MRR, and graded nDCG@K metrics.

## Architecture

```text
IncrementalIndexer
  parse / chunk / projected manifest
        ↓
SQLiteDocumentRegistry
  authoritative atomic mutation
        ↓
chunks + chunk_fts + index_manifests
        ↓
SQLiteBM25Retriever
  BM25 → active validation → stale/duplicate filtering
        ↓
RankedResult
```

`SQLiteIndexMaintainer` is an explicit maintenance boundary. It never trusts current FTS content during rebuild; active immutable Chunk rows are the source of truth.

Post-acceptance hardening reactivates a content-addressed historical Manifest by
moving its row to the append tail inside the same Registry transaction. CJK
queries use bounded substring candidate scoring plus a deterministic coverage
Gate; English terms retain FTS5 prefix matching.

## Main files

- `src/paperclaw/retrieval/query.py`
- `src/paperclaw/retrieval/incremental.py`
- `src/paperclaw/retrieval/integrity.py`
- `src/paperclaw/retrieval/manifest.py`
- `src/paperclaw/retrieval/evaluation.py`
- `src/paperclaw/retrieval/_store.py`
- `tests/unit/test_bm25_incremental_retrieval.py`
- `tests/unit/test_bm25_query_scope.py`
- `tests/fixtures/retrieval_bm25_fixture.json`

## Isolation

No ContextSource, ContextOrchestrator, Citation, answer generation, Prompt assembly, Dense Retrieval, RRF, reranking, PDF/OCR, or online retrieval path is connected by this PR.
