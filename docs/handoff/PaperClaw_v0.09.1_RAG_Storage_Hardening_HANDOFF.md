# PaperClaw v0.09.1 RAG Storage Hardening — Handoff

## Status

Implementation committed on a stacked branch. GitHub Actions is the acceptance source.

## Dependency

- base PR: #24 `feat/v0.09.1-bm25-incremental-retrieval`
- downstream PR: #27 RAG ContextSource / Citation / Grounding

## Main test

`tests/unit/test_rag_storage_hardening.py`

## Validation

```powershell
python -m pytest tests/unit/test_rag_storage_hardening.py -q --basetemp=tmp/pytest
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## Merge order

#24 → this hardening PR → #27.
