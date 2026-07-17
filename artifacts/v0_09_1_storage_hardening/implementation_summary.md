# v0.09.1 RAG Storage Hardening — Implementation Summary

## Delivered

- Windows-style, escaped-space and CJK file URI identity stability;
- cross-process Chunk ID and Corpus hash determinism;
- malformed Markdown fence/heading bounded parsing;
- CJK no-space long-block progress with non-empty unique Chunks;
- injected add-transaction interruption with full rollback assertions;
- concurrent reader old/new committed-snapshot isolation;
- corruption/rebuild equality for counts, Corpus hash and retrieval results.

## Boundary

Regression hardening on top of PR #24. No Dense Retrieval, RRF, reranker, PDF/OCR, online retrieval, Grounding changes, or multi-writer architecture.
