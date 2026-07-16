# v0.09.1 RAG ContextSource / Citation — Implementation Summary

## Delivered

- task-only, stopword-filtered retrieval query extraction;
- BM25 `RetrievalContextSource` registered through the shared ContextSource Registry;
- version/locator/Manifest-bound `CitationAnchor`;
- retrieval candidates with `external_untrusted` trust and retrieval bucket;
- defensive duplicate filtering;
- local pinned abstention constraint for missing/broken evidence;
- ContextOrchestrator budget and trust-section integration;
- label-based Citation Correctness, Unsupported Claim Rate and Abstention Accuracy;
- prompt-injection fixture;
- deterministic offline RAG demo and artifact test.

## Boundary

The module emits structured candidates, anchors and decisions. It does not construct the final Prompt, call a Provider, generate an answer with an LLM, or bypass PR #24 stale/duplicate checks.

## Dependencies

This branch is stacked on BM25 PR #24 and includes the public registration contract from PR #25. It must be rebased after both dependencies merge.
