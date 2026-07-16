# PaperClaw v0.09.1 RAG Document / Index Foundation — Handoff

## Status

Implementation complete for Phase A. Local isolated tests and repository-wide Draft PR CI pass.

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

## Verification result

- Local focused suite: `18 passed`;
- Local compile check: PASS;
- GitHub Actions run `29511938895`;
- Windows repository suite: `523 passed, 0 failed, 0 skipped`;
- Ruff `E9,F63,F7,F82`: PASS;
- no live provider, online retrieval or real-model test was required or executed for this offline Phase A slice.

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
