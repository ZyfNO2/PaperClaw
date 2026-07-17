# PaperClaw v0.09.1 BM25 / Incremental Retrieval — Handoff

## 1. Status

- repository: `ZyfNO2/PaperClaw`;
- branch: `feat/v0.09.1-bm25-incremental-retrieval`;
- Draft PR: `#24`;
- prerequisite: RAG Index Foundation PR #20 merged;
- implementation: complete;
- repository CI: PASS;
- status: `OFFLINE_GO`;
- merge: not requested and not performed.

This Handoff declares the BM25 and incremental-index slice complete. It does not declare ContextSource, Citation, answer generation, Dense Retrieval, or online retrieval complete.

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

## 5. Verification evidence

Validated implementation/docs HEAD before this Handoff closeout:

```text
3442a60615a92ea360c0ef1544a06d19b6dba1a0
```

Repository CI:

```text
GitHub Actions run: 29541314820
Windows pytest: 572 passed, 0 failed, 0 skipped
pytest exit status: 0
Ruff E9/F63/F7/F82: PASS
artifact: pytest-results-29541314820
artifact digest: sha256:f757df67df136d1e269118f53aafcad832b28b5e3e9ad0ff0060660555915ce7
```

`pytest_reportlog.jsonl` was parsed using call-phase records only. Setup and teardown records were not counted as tests.

The deterministic retrieval fixture passed:

```text
Recall@3 = 1.0
MRR      = 1.0
nDCG@3   = 1.0
```

## 6. Known limitations

See `artifacts/v0_09_1_bm25/known_limitations.md`. Important boundaries include lexical-only retrieval, exact-only duplicate filtering, explicit rebuild, no historical-version reactivation, no ContextSource/Citation, and a small regression fixture rather than a production benchmark.

## 7. Next dependency boundary

PR #27 consumes `RankedResult` through a Retrieval `ContextCandidateSource`. It remains a separate stacked Draft and must not make this module construct Prompt sections. Citation and abstention contracts belong to that PR.

PR #25 freezes the shared ContextSource registration contract used by both MCP selection and RAG ContextSource branches.
