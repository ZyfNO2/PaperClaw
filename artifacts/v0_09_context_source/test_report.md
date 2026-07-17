# v0.09 Shared ContextSource Registry — Test Report

## Status

`IMPLEMENTATION_COMPLETE / REPOSITORY_CI_PASS / OFFLINE_GO`

## Covered behavior

- deterministic descriptor snapshots independent of registration order;
- stable descriptor-only SHA-256 fingerprint;
- duplicate source ID rejection;
- post-freeze mutation rejection;
- deterministic priority/source-ID collection order;
- disabled Source isolation;
- bounded and attributed Source exceptions;
- non-`ContextCandidate` output rejection;
- cross-Source candidate ID collision rejection;
- Executor dependency injection and Runtime-time freeze;
- custom orchestrator/Registry constructor conflict rejection;
- external candidate containment in `UNTRUSTED DATA`;
- Context assembly Trace contains source count/fingerprint without candidate content.

## Repository CI

Validated branch HEAD:

```text
b3625c9f0e6d851fb81b09a7444aa91cb0fd26dd
```

```text
GitHub Actions run: 29541766937
Windows pytest call-phase: 567 passed, 0 failed, 0 skipped
pytest exit status: 0
Ruff E9/F63/F7/F82: PASS
artifact: pytest-results-29541766937
artifact digest: sha256:0621460b94791cba0aca7b89c05c1298f76bdff0de2efc9e5a081d0668524aed
```

The test-case count uses only `when == "call"` records from `pytest_reportlog.jsonl`; setup and teardown lifecycle records are excluded.
