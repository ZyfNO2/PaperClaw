# PaperClaw v0.07 Trace Foundation — Known Limitations

## 1. Mistral-specific acceptance is not complete

Live Provider acceptance passed through the supplied OpenCode-compatible
endpoint with `deepseek-v4-flash`. This proves the production adapter and Trace
path, but not Mistral-specific response variants or rate-limit behavior. The
smoke runner now accepts `PAPERCLAW_PROVIDER` so the same contract can be
replayed against Mistral later without changing code.

## 2. Trace is a read-side projection, not a byte-for-byte archive

TraceEvent payloads are intentionally bounded and redacted. They are not suitable for reconstructing the full original HTTP request, Prompt, provider response, file content or shell output.

## 3. Hidden reasoning is not durable Trace state

`ModelTurn.reasoning` may be used transiently by existing runtime behavior, but v0.07 does not persist hidden provider reasoning in TraceEvent payloads.

## 4. Provider reliability has partial live validation

v0.07.1 normalizes request IDs, token usage, finish reasons, retry attempts and
bounded Retry-After behavior. A real OpenCode completion passed. Synthetic HTTP
coverage exercises the error/retry matrix, but a naturally occurring 429,
thinking-only response and retry sequence has not been observed.

## 5. Legacy terminal mapping is heuristic and versioned

Existing v0.04 persistence writes `flow.stopped` with a `stop_reason`. The v0.07 reader maps known completion/failure/budget/blocked reasons into canonical Run terminal events.

Unknown reasons project to `run.stopped` rather than guessing success. Future mappings must preserve v1 compatibility or introduce a new schema version.

## 6. Exact durable stop-request timing is not yet available

The existing persistence boundary lives inside `AgentRuntimeExecutor`, while `QueryEngine.request_stop()` can be called concurrently outside that adapter. v0.07 exports the final stopped terminal state but does not claim an exact durable `run.stop_requested` timestamp/sequence for every cancellation race.

A future lifecycle-recorder refactor should centralize QueryEngine event persistence before adding precise stop-request/stop-accepted spans. v0.07 does not add a second sink or duplicate events to simulate this capability.

## 7. No distributed tracing semantics

`span_id` and `parent_span_id` are optional contract fields. The MVP does not allocate spans, propagate trace context across agents/processes or integrate OpenTelemetry.

## 8. Query and export remain per Run

There is no cross-Run query language, aggregation, pagination API or retention
policy. Inspector and Eval consume one Run at a time.

## 9. Replay and Eval scope is intentionally bounded

Recorded Replay validates recorded control-flow facts without side effects.
Eval provides deterministic trace metrics and explicit thresholds, not an LLM
judge. Guarded Live Replay creates a new Run from a new task and is disabled
unless its confirmation and tool permissions are supplied. Real provider/tool
execution, cancellation during replay and sandbox mutation still require live
acceptance.

## 10. External export has no real collector acceptance yet

The HTTPS exporter is default-off, exact-host allowlisted, redirect-refusing
and bounded by event/payload limits. Offline mocked success and failure paths
are covered. A real collector, DNS rebinding behavior and production TLS/auth
integration have not been validated.

## 11. Generic plugin management is intentionally absent

There is no plugin discovery, installation, permission, sandbox or version negotiation system. A formal Plugin SDK should be considered only after at least two independent real plugins demonstrate a shared contract need.
