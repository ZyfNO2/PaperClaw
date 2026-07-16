# v0.09 MCP Capability Selection — Implementation Summary

## Delivered

- immutable searchable capability metadata;
- deterministic frozen metadata index and fingerprint;
- task/keyword/scope/selection-permission Top-K;
- separate selection eligibility and invocation Permission contracts;
- `external_untrusted` capability ContextCandidates;
- shared ContextSource Registry integration;
- removal of remote description from the base ToolRegistry prompt surface;
- Recall@K, MRR, nDCG@K and Top-1 selection metrics;
- deterministic selection fixture;
- real local stdio MCP end-to-end test through ContextOrchestrator and AgentRuntime.

## Security boundary

The selector never grants invocation permission. It never constructs a Provider Prompt. Remote descriptions are visible only as selected untrusted candidate content; server instructions remain discarded.

## Dependencies

This branch is explicitly stacked on MCP Runtime PR #23 and includes the public registration contract from PR #25. It must be rebased/retargeted after both dependencies merge.
