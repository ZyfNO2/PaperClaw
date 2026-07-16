# v0.09 MCP Capability Selection — Test Report

## Status

`IMPLEMENTATION_COMPLETE / REPOSITORY_CI_PENDING`

## Added coverage

- deterministic capability index snapshot/freeze;
- identity collision rejection;
- task/keyword scoring;
- scope filtering;
- selection allowlist filtering;
- selection does not grant invocation Permission;
- untrusted ContextCandidate conversion;
- remote description isolation from base ToolRegistry descriptions;
- shared ContextSource registration;
- fixed selection fixture metrics;
- full local stdio Fake MCP Server E2E through AgentRuntime and ContextOrchestrator.

## Fixture Gate

Expected assertions:

```text
Recall@3          = 1.0
MRR               = 1.0
nDCG@3            = 1.0
Top-1 Accuracy    = 1.0
```

## Repository CI

Exact pytest count, failures/skips, Ruff conclusion, run ID and artifact digest remain pending while the GitHub Actions connector returns upstream 502. No CI success is inferred from code review or commit creation.
