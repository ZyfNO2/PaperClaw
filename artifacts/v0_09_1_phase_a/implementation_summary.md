# PaperClaw v0.09.1 Phase A — Implementation Summary

## Scope delivered

This slice freezes the write-side contracts required before retrieval is added:

- `DocumentIdentity`
- `DocumentVersion`
- `SourceArtifact`
- `Chunk`
- `IndexManifest`
- deterministic Markdown and plain-text parsers
- heading/paragraph line locators
- deterministic heading-aware chunking
- long-block splitting and bounded overlap
- source hash, chunk content hash, chunk-config hash and active corpus hash
- standalone SQLite document registry
- SQLite FTS5 write-side schema
- atomic add/update/delete contracts
- parser, chunk, registry and manifest unit tests

## Architecture decisions

1. The implementation lives in `paperclaw.retrieval`; it does not modify the v0.04 Context/Session SQLite migration chain.
2. `DocumentIdentity` is stable across content changes. `DocumentVersion` is derived from document identity, source hash and parser version.
3. Source artifacts and prior versions remain immutable. Update/delete deactivates prior rows and removes inactive chunks from FTS5.
4. `IndexManifest` binds schema/index versions, parser versions, chunk config, active counts and an order-independent active corpus hash.
5. Registry mutations run in `BEGIN IMMEDIATE` transactions. Manifest mismatch, duplicate version and inconsistent chunk bundles roll back.
6. FTS5 is populated transactionally, but Phase A exposes no BM25 query API.

## Explicit non-goals

- BM25 query/ranking API
- ContextOrchestrator integration
- CitationAnchor or answer generation
- Dense retrieval, RRF or reranking
- PDF/OCR
- online scholarly search
- stale filtering/rebuild orchestration beyond the frozen schema and active/inactive data model

## Local verification

```text
PYTHONPATH=src python -m pytest -q
18 passed

PYTHONPATH=src python -m compileall -q src tests
PASS
```

Full repository regression and Windows Ruff/pytest are delegated to the Draft PR CI because the execution environment cannot clone GitHub directly.
