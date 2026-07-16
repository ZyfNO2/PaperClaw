# v0.09.1 RAG ContextSource / Citation — Test Report

## Status

`IMPLEMENTATION_COMPLETE / REPOSITORY_CI_PENDING`

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

Exact run ID, pytest test-case count, failures/skips, Ruff result and artifact digest remain pending while the GitHub Actions connector returns upstream 502. No Repository GO claim is made from static review alone.
