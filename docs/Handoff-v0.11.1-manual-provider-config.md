# PaperClaw v0.11.1 Manual Provider Configuration Handoff

## Status

- Repository: `ZyfNO2/PaperClaw`
- Development branch: `agent/manual-provider-and-gate-control`
- Draft PR: `#36`
- Base: `amend/v0.11-frontend-playwright` (follow-up to PR #34)
- Current state: implementation complete; focused offline validation passed; live provider and native Windows acceptance pending

## Scope

This change adds two desktop controls requested after the v0.11 UI acceptance:

1. The ENV/settings dialog can accept an OpenAI-compatible Base URL and API Key, call the provider's `/models` endpoint through Python, and present the returned models in a dropdown.
2. The existing verification switch is made explicit as the shared **Verify & Reflection Gate** control. Disabling it continues to pass `enable_verification_gate=False` into the runtime factory.

## Architecture

- `paperclaw.desktop.provider_config` installs a narrow extension before the desktop host starts.
- The API Key necessarily exists briefly in the password input and bridge request. After a successful connection, the input is cleared and the connected credential is retained only in Python process memory.
- The credential is never returned in public desktop/browser responses and is not persisted to localStorage, sessionStorage, cookies, IndexedDB, traces, or exported events.
- Model discovery uses `GET {base_url}/models` with a bounded 15 second timeout.
- Manual configuration overrides ENV for new desktop runs; callers that supply a complete explicit provider remain unchanged.
- `USE ENV` clears the in-memory manual configuration and restores existing environment-backed behavior.
- The protected loopback browser mode receives the same allow-listed provider methods and static assets.

## Files

- `src/paperclaw/desktop/provider_config.py`
- `src/paperclaw/desktop/bootstrap.py`
- `src/paperclaw/desktop/static/provider-config.js`
- `src/paperclaw/desktop/static/provider-config.css`
- `src/paperclaw/desktop/static/index.html`
- `src/paperclaw/entrypoint.py`
- `scripts/paperclaw_desktop_entry.py`
- `pyproject.toml`
- `tests/unit/desktop/test_provider_config.py`
- `tests/unit/desktop/test_static_assets.py`
- `tests/unit/desktop/test_runtime_factory.py`

## Verification performed

Focused offline validation performed in the available execution environment:

- provider extension tests: `4 passed in 0.14s`;
- `node --check src/paperclaw/desktop/static/provider-config.js`: passed;
- provider UI static secret/persistence scan: passed;
- disabled Verify/Reflection gate forwarding smoke: passed;
- Python syntax compilation for the new Python modules and tests: passed;
- HTML parser smoke: passed.

The repository workflows are filtered to pull requests targeting `main`. This PR intentionally targets the active v0.11 frontend branch, so GitHub Actions did not execute for this exact head. Full repository regression and Windows package CI therefore remain `NOT VERIFIED` for PR #36.

Recommended validation after PR #34 is merged or the workflow base filter is expanded:

```bash
python -m pytest -q tests/unit/desktop/test_provider_config.py
python -m pytest -q tests/unit/desktop/test_static_assets.py
python -m pytest -q tests/unit/desktop/test_runtime_factory.py
python -m pytest -q
python -m ruff check .
```

## Manual acceptance still required

Use a real OpenAI-compatible provider account on Windows:

1. Open Settings.
2. Enter Base URL and API Key.
3. Click **CONNECT & LOAD MODELS**.
4. Confirm the model dropdown contains only models returned by the provider.
5. Select a model and run a simple task.
6. Confirm the run header and model event metadata use the selected model.
7. Disable **Enable verification & reflection gate** and confirm no verification/reflection lifecycle is executed.
8. Export the trace and confirm the API Key is absent.
9. Click **USE ENV** and confirm the original `PAPERCLAW_*` configuration is restored.

A real provider request is not represented by the offline tests.
