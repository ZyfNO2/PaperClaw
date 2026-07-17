# PaperClaw v0.09 MCP Transport Hardening — Handoff

## Status

Implementation committed. Repository CI is the acceptance source.

## Branch

`test/v0.09-mcp-transport-hardening`

## Files

- `tests/fixtures/fake_mcp_hardening_server.py`
- `tests/unit/test_mcp_transport_hardening.py`
- `Plan/PaperClaw_v0.09_MCP_Transport_Hardening_SOP.md`
- `artifacts/v0_09_transport_hardening/implementation_summary.md`

## Required validation

```powershell
python -m pytest tests/unit/test_mcp_transport_hardening.py -q --basetemp=tmp/pytest
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## Merge ordering

Merge before MCP Runtime and MCP Capability Selection are finalized, then rebase those branches onto the hardened main.
