# v0.09 Phase A — MCP Protocol Foundation Artifact

## Status

`PHASE_A_GO / LOCAL_OFFLINE_PASS / REPOSITORY_CI_PASS`

This artifact covers only the protocol foundation Phase A. It does not claim the
complete v0.09 MCP Tool Gateway MVP.

## Implemented files

- `src/paperclaw/mcp/contracts.py`
- `src/paperclaw/mcp/schema.py`
- `src/paperclaw/mcp/transport.py`
- `src/paperclaw/mcp/session.py`
- `src/paperclaw/mcp/__init__.py`
- `tests/fixtures/fake_mcp_server.py`
- `tests/unit/test_mcp_protocol_foundation.py`
- `Plan/PaperClaw_v0.09_MCP_Protocol_Foundation_Phase_A_SOP.md`

## Architecture decisions

1. Use the official MCP `2025-11-25` lifecycle and stdio framing.
2. Keep Phase A synchronous and single-flight; no async framework or request multiplexing.
3. Treat transport/protocol corruption, timeout and disconnect as terminal session failures.
4. Keep unsupported tool schema as a discovery rejection without committing a partial descriptor set.
5. Canonicalize and freeze supported schema before hashing.
6. Discard Server instructions and all unsupported capability payloads.
7. Accept only text and object structured tool results.
8. Keep the package dependency-free and isolated from existing runtime modules.

## Local verification

Environment:

- execution container Linux;
- Python 3.13.5;
- tests use a real local subprocess and stdio pipes;
- no network, external MCP Server, Provider, ToolRegistry, Permission or Agent Runtime involved.

Executed:

```text
PYTHONPATH=src python -m pytest tests/unit/test_mcp_protocol_foundation.py -q
```

Result:

```text
16 passed in 17.40s
```

Also executed:

```text
python -m compileall -q src/paperclaw/mcp tests
```

Result: PASS.

Executed:

```text
PYTHONPATH=src python -m ruff check src/paperclaw/mcp \
  tests/unit/test_mcp_protocol_foundation.py \
  tests/fixtures/fake_mcp_server.py --select E9,F63,F7,F82
```

Result: PASS (`All checks passed!`).

Repository CI source of truth:

- final implementation commit: `f872a815f3ecf8f358a442580716fc46ab0e85f2`;
- run: `29513038780`;
- Windows Server 2025 / Python 3.12;
- pytest: `521 passed, 0 failed, 0 skipped`, exit status `0`;
- Ruff: PASS;
- artifact digest: `sha256:dc3544da93c5e235554d942264146bb2e2facceb3bd0261f57bbd9bd531a0a15`.

## Test classification

- Contract normalization tests: offline unit tests.
- Lifecycle/error tests: deterministic local subprocess integration tests using
  the fake stdio MCP Server.
- These are not a real third-party MCP Server E2E and are not described as such.

## Known limitations

- Only local stdio transport.
- One active request at a time.
- One Server per session; no router.
- No reconnect, capability cache, stale refresh or health scoring.
- Conservative JSON Schema subset rejects `$ref`, composition and other advanced keywords.
- No argument validation against normalized schema; that belongs to Registry/validation Phase B.
- No ToolRegistry, Permission, Run Budget, Trace or Agent Runtime connection.
- No Resources / Prompts.
- No image/audio/resource result storage.
- No remote write operation support or idempotency policy.
- No external Server interoperability validation yet.

## Stop condition

Phase A stops after protocol contracts, local transport, deterministic fake
Server and failure tests pass. Registry/Permission/Context work must be a
separate PR.
