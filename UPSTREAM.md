# PocketFlow Vendored Core — Upstream Provenance

This directory vendors a snapshot of [PocketFlow](https://github.com/The-Pocket-Flow-Development/PocketFlow)
so PaperClaw does not depend on the external `pocketflow` PyPI package.

## Fixed upstream commit

- Upstream commit: `43ef382bb0c9dae8167528618bb40f5a3f9a28a5`
- Vendored file: `src/pocketflow/__init__.py`
- Git blob SHA of vendored file: `0b71858bfb9c0d8d02c5eb0b692d8b788af342e3`
- Stub file `src/pocketflow/__init__.pyi` is PaperClaw-maintained; it is NOT
  part of the upstream snapshot and is allowed to diverge (Addendum §8).

These values are pinned by `tests/test_pocketflow_vendor_integrity.py`
(Addendum §7). Modifying `src/pocketflow/__init__.py` without bumping both
the upstream commit and the expected blob SHA will fail that test.

## Modification policy

Per Addendum §1:

- PaperClaw MUST NOT modify `src/pocketflow/__init__.py`.
- PaperClaw Session / Checkpoint / Trace / Context / Permission / Tool
  fields MUST NOT be added to the vendored core.
- All PaperClaw runtime features live under `src/paperclaw/`.

## Upgrade procedure (Addendum §7.3)

When a future version needs to upgrade PocketFlow:

1. Submit the vendored core upgrade as a single dedicated commit; do not
   mix it with PaperClaw Runtime changes.
2. Update the upstream commit and blob SHA in this file and in
   `tests/test_pocketflow_vendor_integrity.py`.
3. Run the full PocketFlow contract test suite
   (`tests/test_pocketflow_contract.py`).
4. Generate a behavior-diff report (parity test results before/after).
5. Document any node-identity or transition semantics that changed.
