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
- projection, JSONL and HTTP exporter suppression of Prompt, reasoning, file
  content, tool output, stdout and stderr full text;
- a hard upper bound of 10 Provider attempts.

## Local and live results

- full local pytest: `465 passed, 5 skipped` before the final security patch;
- post-patch focused security/reliability suite: `53 passed`;
- CI-equivalent high-signal Ruff: PASS;
- real OpenCode `deepseek-v4-flash` durable Trace smoke: PASS;
- real-model Live Replay without tools: PASS;
- real-model Live Replay with one isolated `file_write`: PASS;
- real-model Live Replay with one safe PowerShell `Get-Location`: PASS;
- missing mutating-tool authorization: correctly denied before target DB creation;
- real HTTPS loopback collector POST: PASS (202, request ID, token absent).

## Acceptance boundary

These results establish offline validation plus the listed OpenCode, loopback
HTTPS, and isolated Live Replay gates. They do not establish Mistral-specific
429/thinking-only behavior, a third-party production collector, or physical TUI
user-experience acceptance. Those remain explicitly separate.
