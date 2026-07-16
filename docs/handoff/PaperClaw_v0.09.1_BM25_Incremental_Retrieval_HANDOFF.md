# PaperClaw v0.09.1 BM25 / Incremental Retrieval — Handoff

## 1. Status

- repository: `ZyfNO2/PaperClaw`;
- branch: `feat/v0.09.1-bm25-incremental-retrieval`;
- Draft PR: `#24`;
- prerequisite: RAG Index Foundation PR #20 merged;
- implementation: complete;
- repository CI: pending due GitHub connector upstream 502;
- merge: not requested and not performed.

This Handoff does not declare Repository GO until the final branch HEAD passes full Windows pytest and Ruff.

## 2. Delivered

- `RetrievalRequest`, `RetrievalCandidate`, `RankedResult`;
- deterministic FTS5 BM25 query and stable tie-breaking;
- pre-pool document scope filtering;
- pinned Manifest/corpus snapshot validation;
- active Document/Version/Chunk validation;
- exact FTS payload validation including heading and text;
- stale and exact duplicate filtering;
- incremental add/update/delete/unchanged-noop orchestration;
- projected Manifest calculation;
- existing Registry transaction reuse;
- strict persisted Manifest validation;
- exact FTS/Manifest integrity report;
- broken index rebuild from active immutable Chunks;
- deterministic retrieval fixture;
- Recall@K, MRR, graded nDCG@K.

## 3. Key decisions

1. **No second writer**: `SQLiteDocumentRegistry` remains authoritative for all document/version/chunk mutations.
2. **Read-side isolation**: BM25 querying is implemented by `SQLiteBM25Retriever` and does not mutate registry state.
3. **Stale means exact mismatch**: active flags alone are insufficient; FTS identifiers, heading, and text must match persisted Chunk data.
4. **Scope before pool**: document constraints enter the FTS SQL before `LIMIT`, preventing unrelated documents from starving the requested scope.
5. **Snapshot pinning**: callers may fail closed on Manifest/corpus drift.
6. **Exact duplicate baseline**: content-hash duplicates are removed after ranking; no near-duplicate heuristic is introduced.
7. **Explicit repair**: query execution does not silently rewrite storage. Maintenance is a separate, auditable operation.
8. **Chunk rows are rebuild authority**: FTS data is disposable; active immutable Chunk data is not.
9. **Manifest is verified data**: schema/index version/state/content hash/count/corpus inconsistencies mark the index broken.
10. **No Prompt boundary crossing**: this PR stops before ContextSource, Citation, and answer generation.

## 4. Main files

```text
src/paperclaw/retrieval/query.py
src/paperclaw/retrieval/incremental.py
src/paperclaw/retrieval/integrity.py
src/paperclaw/retrieval/manifest.py
src/paperclaw/retrieval/evaluation.py
src/paperclaw/retrieval/_store.py
src/paperclaw/retrieval/__init__.py

tests/unit/test_bm25_incremental_retrieval.py
tests/unit/test_bm25_query_scope.py
tests/fixtures/retrieval_bm25_fixture.json
```

## 5. Verification state

Completed:

- deterministic code review against Phase A contracts;
- independent SQLite FTS5 scoped-query smoke;
- repository tests and metric assertions committed.

Pending:

- final GitHub Actions run ID;
- full pytest test-case count;
- failures/skips;
- Ruff conclusion;
- pytest artifact digest.

The connector returned upstream 502 for both current and historical Actions queries, so no CI result has been inferred or fabricated.

## 6. Known limitations

See `artifacts/v0_09_1_bm25/known_limitations.md`. Important boundaries include lexical-only retrieval, exact-only duplicate filtering, explicit rebuild, no historical-version reactivation, no ContextSource/Citation, and a small regression fixture rather than a production benchmark.

## 7. Next dependency boundary

PR 6 may consume `RankedResult` through a Retrieval `ContextCandidateSource`, but must not make this module construct Prompt sections. Citation and abstention contracts belong to PR 6.

PR 5 and PR 6 need a shared ContextSource registration contract before either modifies executor dependency injection. That contract should be frozen separately so MCP and RAG adapters register sources without owning Prompt assembly.
