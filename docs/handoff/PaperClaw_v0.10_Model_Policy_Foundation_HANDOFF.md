# PaperClaw v0.10 Static Model Policy Foundation — Handoff

## Status

Contracts, deterministic router and unit tests are committed. Runtime integration is intentionally deferred.

## Files

- `src/paperclaw/model_policy/contracts.py`
- `src/paperclaw/model_policy/router.py`
- `src/paperclaw/model_policy/__init__.py`
- `tests/unit/test_model_policy_foundation.py`
- `Plan/PaperClaw_v0.10_Model_Policy_Foundation_SOP.md`

## Validation

```powershell
python -m pytest tests/unit/test_model_policy_foundation.py -q --basetemp=tmp/pytest
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## Next slice

After v0.09/v0.09.1 integration stabilizes, add a separate Runtime wiring PR. It must preserve explicit decision/fallback Trace and must route context overflow back through v0.08 reduction rather than silently dropping constraints.
