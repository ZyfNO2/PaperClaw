# Test Report

## Stacked-tree validation

- Dependency base: PR #24 `feat/v0.09.1-bm25-incremental-retrieval`
- Temporary CI target: `main`
- GitHub Actions run: `29550866096`
- Windows Server 2025 / Python 3.12
- pytest call-phase cases: `579 passed, 0 failed, 0 skipped`
- pytest exit status: `0`
- Ruff E9/F63/F7/F82: `PASS`
- artifact: `pytest-results-29550866096`
- artifact ID: `8395710592`
- artifact digest: `sha256:b9231ce1071c3dbf4c7e4fe21365a08c8bd8f5d9ffdb87c60e7e0afc55588cab`

The exact count was parsed from `pytest_reportlog.jsonl` using only call-phase `TestReport` records.

This validates the complete #24 + #30 stacked tree. PR #24 has now merged into `main`, and PR #30 has been retargeted to `main`. This documentation commit triggers final head verification against the merged dependency chain before PR #30 is merged.
