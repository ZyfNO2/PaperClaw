# v0.09 Phase A Test Report

## Local offline verification

Environment: Linux, Python 3.13.5.

```text
PYTHONPATH=src python -m pytest tests/unit/test_mcp_protocol_foundation.py -q
16 passed in 17.40s
```

```text
python -m compileall -q src/paperclaw/mcp tests
PASS
```

```text
PYTHONPATH=src python -m ruff check src/paperclaw/mcp \
  tests/unit/test_mcp_protocol_foundation.py \
  tests/fixtures/fake_mcp_server.py --select E9,F63,F7,F82
All checks passed!
```

## Coverage

- normal connect/initialize/discover/call/close lifecycle;
- tools/list pagination;
- deterministic immutable schema normalization;
- unsupported schema fail-closed;
- request timeout;
- subprocess disconnect;
- invalid JSON;
- mismatched response ID;
- ambiguous result/error response;
- protocol version mismatch;
- invalid initialize response;
- unsupported tool result content;
- secret environment values excluded from config fingerprint.

## Classification

Contract tests are offline unit tests. Lifecycle tests launch a deterministic
local subprocess over real stdio pipes. They are not third-party MCP Server E2E.

## Repository CI

Final implementation commit: `f872a815f3ecf8f358a442580716fc46ab0e85f2`.

- GitHub Actions run: `29513038780`;
- runner: Windows Server 2025;
- Python: 3.12;
- pytest: `521 passed, 0 failed, 0 skipped`;
- exit status: `0`;
- Ruff E9/F63/F7/F82: PASS;
- artifact: `pytest-results-29513038780`;
- artifact digest: `sha256:dc3544da93c5e235554d942264146bb2e2facceb3bd0261f57bbd9bd531a0a15`.

The machine-readable `pytest_reportlog.jsonl` was downloaded and counted; the
result is not inferred from a commit message or PR description.
