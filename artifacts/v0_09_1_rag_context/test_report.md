# v0.09.1 RAG ContextSource / Citation — Test Report

## Status

`IMPLEMENTATION_COMPLETE / MAIN_TARGET_CI_PENDING`

## Dependency state

- PR #24 BM25 / Incremental Retrieval: merged;
- PR #25 ContextSource Registration Contract: merged;
- PR #30 RAG Storage Hardening: merged;
- shared ContextSource files synchronized to current `main`.

## Added coverage

- CitationAnchor binds Manifest/corpus/Chunk/Version/URI/locator/content hash;
- retrieval result conversion to untrusted evidence candidates;
- ContextOrchestrator retrieval budget allocation;
- malicious document instruction remains in UNTRUSTED DATA;
- no-answer query produces pinned local abstention constraint;
- duplicate content produces one anchor;
- stale old-version token produces abstention;
- citation label resolution;
- Citation Correctness and Unsupported Claim Rate;
- deterministic offline RAG demo output and injection containment.

## Demo Gate

Expected assertions:

```text
answerable = true
citation_correctness = 1.0
unsupported_claim_rate = 0.0
abstention_accuracy = 1.0
injection_in_runtime_protocol = false
injection_contained_in_untrusted_data = true
```

## Repository CI

This commit triggers final GitHub Actions verification against current `main`. Exact pytest call-phase count, Ruff result and artifact digest will be recorded in the PR before merge.
