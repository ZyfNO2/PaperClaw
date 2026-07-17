# PaperClaw v0.08 Context / Combined Hardening — Handoff

## Status

Implementation committed; GitHub Actions is the acceptance source.

## Main test

`tests/property/test_context_combined_hardening.py`

## Validation

```powershell
python -m pytest tests/property/test_context_combined_hardening.py -q --basetemp=tmp/pytest
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## Merge ordering

Process before final ContextSource Registry, MCP Capability Selection, and RAG ContextSource integration PRs are merged. Rebase those branches if this hardening exposes production fixes.
