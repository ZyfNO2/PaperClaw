# PaperClaw v0.07 Trace Foundation — Known Limitations

## 1. Live Mistral acceptance is not complete

The current execution environment cannot resolve the configured Mistral hostname. The key has not been validated and no live completion has passed. Use `scripts/run_v0_07_mistral_trace_smoke.py` in a network-enabled environment.

## 2. Trace is a read-side projection, not a byte-for-byte archive

TraceEvent payloads are intentionally bounded and redacted. They are not suitable for reconstructing the full original HTTP request, Prompt, provider response, file content or shell output.

## 3. Hidden reasoning is not durable Trace state

`ModelTurn.reasoning` may be used transiently by existing runtime behavior, but v0.07 does not persist hidden provider reasoning in TraceEvent payloads.

## 4. Provider usage fields are not normalized

v0.07 records explicit provider/model identity and model-call duration. It does not yet normalize request IDs, token usage, finish reasons, retry attempts, rate-limit headers or cost.

Those belong to the planned Provider Reliability plugin.

## 5. Legacy terminal mapping is heuristic and versioned

Existing v0.04 persistence writes `flow.stopped` with a `stop_reason`. The v0.07 reader maps known completion/failure/budget/blocked reasons into canonical Run terminal events.

Unknown reasons project to `run.stopped` rather than guessing success. Future mappings must preserve v1 compatibility or introduce a new schema version.

## 6. Exact durable stop-request timing is not yet available

The existing persistence boundary lives inside `AgentRuntimeExecutor`, while `QueryEngine.request_stop()` can be called concurrently outside that adapter. v0.07 exports the final stopped terminal state but does not claim an exact durable `run.stop_requested` timestamp/sequence for every cancellation race.

A future lifecycle-recorder refactor should centralize QueryEngine event persistence before adding precise stop-request/stop-accepted spans. v0.07 does not add a second sink or duplicate events to simulate this capability.

## 7. No distributed tracing semantics

`span_id` and `parent_span_id` are optional contract fields. The MVP does not allocate spans, propagate trace context across agents/processes or integrate OpenTelemetry.

## 8. Export is per Run

There is no cross-Run query language, aggregation, pagination API or retention policy. Eval and Inspector plugins should first consume the per-Run reader rather than expanding the core prematurely.

## 9. Replay and Eval are not implemented

Loading JSONL only validates data. It never executes a model, tool, patch, shell command or checkpoint. Recorded Replay, live re-execution and Eval remain separate later work.

## 10. Generic plugin management is intentionally absent

There is no plugin discovery, installation, permission, sandbox or version negotiation system. A formal Plugin SDK should be considered only after at least two independent real plugins demonstrate a shared contract need.
