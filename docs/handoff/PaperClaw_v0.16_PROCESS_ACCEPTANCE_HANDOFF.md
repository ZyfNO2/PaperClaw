# PaperClaw v0.16 Process Acceptance & Recovery Handoff

## Branch relationship

- Parent PR: #40
- Parent head: `18cf7be41232d6ad2646d9f66b0c6fd4c3f81a43`
- Branch: `feat/v0.16-process-acceptance-recovery`
- PR: #41

This is a stacked PR. Merge or integrate #40 first, then retarget/rebase #41 and rerun exact-head validation.

## Production path exercised

```text
separate Mock Provider process
  → OpenAI-compatible HTTP /v1/chat/completions
  → OpenAICompatibleModel
  → real paperclaw.service.entrypoint process
  → Uvicorn/FastAPI HTTP API
  → DurableRunApplicationService
  → SQLite state, lease, transition and event store
  → public GET/SSE replay
```

## Restart scenario

1. Submit one durable run through `POST /v1/runs`.
2. Wait until the separate Provider process receives and blocks the first model call.
3. Kill the PaperClaw service process without graceful shutdown.
4. Wait until the persisted worker lease expires.
5. Start a new PaperClaw process against the same SQLite database.
6. Recovery reconciliation requeues the same durable run ID.
7. The second Provider call returns a deterministic completion.
8. The original run reaches `completed`, and persisted events include `service.run.reconciled` and exactly one `service.run.finalized` event.

## CLI controls added

- `--lease-seconds`
- `--heartbeat-seconds`
- `--queue-timeout-seconds`
- `--run-timeout-seconds`

The heartbeat must be strictly less than the lease duration. All timing values must be positive.

## Test locations

- `tests/helpers/mock_openai_provider.py`
- `tests/e2e/service/test_process_acceptance.py`
- `tests/unit/service/test_service_entrypoint.py`
- `.github/workflows/v016-process-acceptance.yml`

## Next production priorities

1. authenticated run ownership and tenant isolation;
2. Provider circuit breaker and explicit retry classification at the service boundary;
3. DNS-resolution-aware network egress enforcement;
4. a subprocess or worker-process execution adapter for hard Provider/tool timeout isolation;
5. PostgreSQL durable storage and an external queue adapter when multi-host execution is required.
