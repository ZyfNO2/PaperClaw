# PaperClaw v0.07 Trace Foundation — Known Limitations

## 1. Live Mistral acceptance is not complete

The current execution environment cannot resolve the configured Mistral hostname. The key has not been validated and no live completion has passed. Use `scripts/run_v0_07_mistral_trace_smoke.py` in a network-enabled environment.

## 2. Trace is a read-side projection, not a byte-for-byte archive

TraceEvent payloads are intentionally bounded and redacted. They are not suitable for reconstructing the full original HTTP request, Prompt, provider response, file content or shell output.

## 3. Hidden reasoning is not durable Trace state

`ModelTurn.reasoning` may be used transiently by existing runtime behavior, but v0.07 does not persist hidden provider reasoning in TraceEvent payloads.

## 4. Provider reliability is implemented but not live-validated

v0.07.1 normalizes request IDs, token usage, finish reasons, retry attempts and
bounded Retry-After behavior. The offline HTTP/error matrix is covered, but a
real Mistral 429, thinking-only response and retry sequence have not been
observed because live provider connectivity remains blocked.

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
