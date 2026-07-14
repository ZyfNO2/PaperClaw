# Real LLM Artifact Redaction Report

This artifact bundle is produced by ``scripts/run_v0_05_real_llm_acceptance.py``.

Redactions applied before writing:

- ``PAPERCLAW_API_KEY`` is never written to disk.
- Authorization headers are not captured because the runner never intercepts HTTP traffic.
- Absolute workspace paths in tool metadata are replaced with ``<workspace>/<basename>``.
- Environment variables other than provider name/base URL/model are not recorded.
- Provider response request IDs are not captured.

If you rerun the script with a real provider, these files will be overwritten.
