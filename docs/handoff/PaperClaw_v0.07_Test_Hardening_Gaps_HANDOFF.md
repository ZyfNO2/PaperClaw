# PaperClaw v0.07 Test Hardening Gaps — Handoff

## Repository state

- Repository: `ZyfNO2/PaperClaw`
- Base: `main@ec1ecbeaf37c0e6ea85a07c12446b3d8f9b8e409`
- Branch: `test/v0.07-hardening-gaps`
- Pull request: `#17` (Draft)
- Merge status: not merged
- Status: **OFFLINE GO**

## Why this branch exists

Merged PR #13 already hardened the v0.07.x stack with Provider failure matrices, replay corruption/determinism, exporter limits, Eval threshold boundaries, 10k Inspector checks and Live Replay isolation.

This branch closes only the remaining gaps:

1. frozen Golden Eval fixtures;
2. actual local mock collector server;
3. Hypothesis property-based Trace fuzzing;
4. one full runtime-to-trace integration path.

## Branch topology

At branch creation time:

```text
main@ec1ecbe  (#5–#11 + #13 merged)
├─ PR #14  Global Verify, based on old main and requiring update
├─ PR #15  MultiAgent View Adapter, cleanly based on current main
├─ PR #16  MultiAgent TUI, code-descendant of #15 but PR base set to main
└─ PR #17  v0.07 test hardening gaps, independent from #14–#16
```

PR #17 does not modify the MultiAgent or TUI files owned by #14–#16.

## Files added or changed

- `pyproject.toml`
- `Plan/PaperClaw_v0.07_Test_Hardening_Gaps_SOP.md`
- `tests/property/test_trace_properties.py`
- `tests/fixtures/eval_golden/manifest.json`
- `tests/fixtures/eval_golden/success.trace.jsonl`
- `tests/fixtures/eval_golden/provider_retry.trace.jsonl`
- `tests/fixtures/eval_golden/tool_failure.trace.jsonl`
- `tests/fixtures/eval_golden/partial.trace.jsonl`
- `tests/integration/test_eval_golden_dataset.py`
- `tests/integration/test_external_exporter_mock_server.py`
- `tests/integration/test_v0_07_full_trace_pipeline.py`
- `artifacts/v0_07/test_hardening_gaps_report.md`
- `docs/handoff/PaperClaw_v0.07_Test_Hardening_Gaps_HANDOFF.md`

## Validation checkpoint

GitHub Actions run `29453571098` / #149 on commit `a043c7feba619c3d9b6dec4bf4678e002a857412`:

- pytest: **485 passed, 0 failed, 0 skipped**;
- Ruff high-signal gate: **PASS**;
- artifact ID: `8358539315`;
- digest: `sha256:c9227a78fe502de82d97f6d363bc9971ff5f09aed1410caf67e5c4ffb539b658`.

A final branch-head CI run is required after this Handoff and report commit.

## Review notes

### Property tests

Hypothesis is a dev-only dependency. Generated examples are bounded and deadline checks are disabled to avoid machine-speed flakiness; the overall CI timeout remains authoritative.

### Mock collector

The logical production endpoint remains `https://collector.test/...` and must pass production validation. A test-only transport routes the already-validated request to a loopback HTTP server. No production policy is weakened and no real network service is contacted.

### Golden data

Golden files intentionally freeze selected semantic outputs, not wall-clock values or incidental formatting. Updating them should require a documented Eval contract decision.

### Full integration

The scenario uses the real FileWriteTool against `tmp_path`, but no shell, external Provider or live replay action.

## Next action

1. Check final head CI after documentation commits.
2. Keep PR #17 Draft for owner review.
3. Do not merge PR #17 through PR #16 or any stacked MultiAgent branch; it is independently based on `main`.
4. After merge, rebase/update PR #14 and review PR #15 before PR #16.
