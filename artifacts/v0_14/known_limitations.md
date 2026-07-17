# PaperClaw v0.14 Known Limitations

- The committed cases are deterministic fixtures, not a statistically representative benchmark.
- Recorded variants measure evaluation plumbing, not current live-model quality.
- Existing BM25 retrieval, MCP and Context Orchestration implementations are not yet connected through production adapters.
- Recall@K currently reports a fixed maximum K of 5 based on available hits; configurable experiment K is a future integration slice.
- Claim matching is normalized substring matching, not semantic entailment.
- Citation correctness checks source identity, not whether every cited passage logically proves the claim.
- No LLM-as-judge is used; this avoids nondeterminism but limits semantic scoring.
- No vector database, reranker or hybrid retrieval plugin is implemented.
- Live latency and cost measurements are not claimed.
- Dataset governance, larger splits and domain-specific benchmark validity remain future work.
