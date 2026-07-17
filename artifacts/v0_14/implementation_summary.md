# PaperClaw v0.14 Research Demo & Eval Implementation Summary

## Status

**IMPLEMENTED / OFFLINE VALIDATED**

Implementation verification head: `1a225ce5aa5ebcc53729607fda19834cd50e5adf`.

## Delivered

- Versioned JSONL dataset, evidence, claim and result contracts.
- Strict type validation with optional list fields defaulting safely.
- Stable dataset and report SHA-256 digests.
- Secret-safe result metadata.
- Recorded evaluation variants for deterministic replay.
- Recall@K and MRR retrieval metrics.
- Required-claim coverage and forbidden-claim rate.
- Citation correctness, citation completeness and unsupported-claim rate.
- Model/tool/MCP call, latency and context-size metrics.
- Static metric plugin registry with failure preservation.
- Retrieval, MCP capability and report-renderer protocols.
- JSON/Markdown rendering and report comparison.
- `paperclaw research-eval` and `paperclaw-research-eval` entrypoints.
- Canonical evidence-backed and no-retrieval fixtures.
- Byte-reproducible canonical artifact generator.

## Canonical recorded comparison

- Dataset digest: `a0156e6d5c73ebde49b753b35ebc3337900897ab0f2c6f16b1e9cfcd94e8d774`.
- Report digest: `68a82cc177bbe465515c11e727b9b351469f365de1a31d7e3972f4e0c5bbdbbc`.
- `baseline_no_retrieval` mean Recall@K: `0.0`.
- `bm25_mcp_verify` mean Recall@K: `1.0`.

These figures are deterministic fixture measurements, not live model benchmark claims.

## Verification

- Repository-wide Windows non-live pytest: `706 passed` on workflow run `29614255414`.
- Ruff correctness gate: PASS.
- Generator executed twice in separate directories and produced byte-identical JSON and Markdown.

## Not claimed

- General scientific benchmark validity.
- Live LLM quality.
- Production adapters to existing BM25, MCP or Context Orchestration paths.
- Vector retrieval, reranking or LLM-as-judge.
