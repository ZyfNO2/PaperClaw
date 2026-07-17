# v0.09 MCP Capability Selection — Test Report

## Status

`IMPLEMENTATION_COMPLETE / REPOSITORY_CI_RUNNING`

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

## Repository CI strategy

The repository workflow only listens to pull requests whose base is `main`. PR #26 is normally stacked on the MCP Runtime branch, so it is temporarily retargeted to `main` solely to execute the identical full Windows pytest and Ruff workflow. After validation and documentation closeout, the Draft PR will be restored to its dependency branch.

Exact test counts, failures/skips, Ruff conclusion, run ID and artifact digest remain pending until that run completes.
