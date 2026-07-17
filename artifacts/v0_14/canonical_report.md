# PaperClaw Research Evaluation

- Dataset digest: `a0156e6d5c73ebde49b753b35ebc3337900897ab0f2c6f16b1e9cfcd94e8d774`
- Report digest: `68a82cc177bbe465515c11e727b9b351469f365de1a31d7e3972f4e0c5bbdbbc`
- Cases: 2

## baseline_no_retrieval

- Version: `recorded-v1`
- Failed cases: 0

| Metric | Mean |
|---|---:|
| citation_completeness | 0.500000 |
| citation_correctness | 1.000000 |
| forbidden_claim_rate | 0.000000 |
| latency_ms | 32.500000 |
| mcp_calls | 0.000000 |
| model_calls | 1.000000 |
| mrr | 0.000000 |
| recall_at_k | 0.000000 |
| required_claim_coverage | 0.250000 |
| selected_context_items | 0.000000 |
| tool_calls | 0.000000 |
| unsupported_claim_rate | 0.500000 |

## bm25_mcp_verify

- Version: `recorded-v1`
- Failed cases: 0

| Metric | Mean |
|---|---:|
| citation_completeness | 1.000000 |
| citation_correctness | 1.000000 |
| forbidden_claim_rate | 0.000000 |
| latency_ms | 100.000000 |
| mcp_calls | 1.000000 |
| model_calls | 1.500000 |
| mrr | 1.000000 |
| recall_at_k | 1.000000 |
| required_claim_coverage | 1.000000 |
| selected_context_items | 1.500000 |
| tool_calls | 0.500000 |
| unsupported_claim_rate | 0.000000 |
