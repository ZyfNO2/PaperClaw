# PaperClaw v0.09.1 RAG Document / Index Foundation — Handoff

## Status

Implementation complete for Phase A. Local isolated tests pass. GitHub Actions status must be read from the Draft PR associated with `feat/v0.09.1-rag-index-foundation`.

## Branch

`feat/v0.09.1-rag-index-foundation`

## Delivered

- immutable document, artifact, version, chunk and manifest contracts;
- deterministic Markdown/plain-text parsing;
- source line, heading-path and paragraph locators;
- deterministic chunk IDs and hashes;
- long-block and overlap behavior under a hashed `ChunkConfig`;
- standalone SQLite registry and FTS5 schema;
- transactional add/update/delete with active-version semantics;
- Manifest count/parser/corpus validation;
- focused unit tests and implementation summary.

## Main files

- `src/paperclaw/retrieval/contracts.py`
- `src/paperclaw/retrieval/parsers.py`
- `src/paperclaw/retrieval/chunking.py`
- `src/paperclaw/retrieval/registry.py`
- `tests/unit/test_retrieval_foundation.py`

## Verification commands

```powershell
python -m pytest tests/unit/test_retrieval_foundation.py -q --basetemp=tmp/pytest
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## Known limits

- Markdown parser covers ATX headings, paragraphs and fenced-code boundaries; it is not a full CommonMark AST parser.
- Registry stores and synchronizes FTS5 rows but intentionally provides no retrieval API.
- Soft-deactivated versions/chunks are retained for future provenance and citation work.
- Phase B must implement BM25 query, stale/duplicate filtering, incremental orchestration and ContextSource integration without changing these identities.

## Next developer steps

1. Treat the contracts and SQLite schema in this branch as the Phase A compatibility boundary.
2. Add BM25 retrieval as a read-side adapter; do not let it mutate registry state.
3. Filter to active chunks and preserve `version_id`, locator, source hash and chunk-config hash in every candidate.
4. Add rebuild/integrity workflows and graded retrieval fixtures in subsequent PRs.
