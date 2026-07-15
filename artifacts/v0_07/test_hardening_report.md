# PaperClaw v0.07.x Test Hardening Report

## Scope

This acceptance pass covers the stacked v0.07 Foundation and v0.07.1-v0.07.6
modules before merging them individually into `main`.

## Automated coverage added

- Provider HTTP classification for 400/401/403/404/408/409/429/5xx;
- strict RetryPolicy type/range validation and malformed response shapes;
- invalid Retry-After and usage normalization;
- exporter unsafe endpoints, sanitized HTTP failures and payload limits;
- Recorded Replay corruption cases and deterministic results;
- Eval inclusive threshold boundaries;
- Inspector 10,000-event aggregation with bounded rendering;
- Inspector suppression of prompt/reasoning/tool-output/header fields;
- Live Replay source-database hash stability and target identity isolation.

## Acceptance boundary

Automated local and GitHub CI results may establish `offline_validated` only.
They do not establish live Mistral, real collector, real tool mutation, physical
TUI or production-network acceptance. Those items are listed in
`known_limitations.md` and must be completed separately.
