# v0.31 Implementation Status

Status: implementation complete enough for CI; acceptance pending.

Branch: `feat/v0.31-e2e-eval-messagebus`
Base: `main @ 5891d1efbc840aa81ba2a2c1c3e06ab7619cb9f2`

## Implemented

- durable bus-driven team request entrypoint;
- existing Coordinator/Worker/Reviewer composition;
- live team-event mirroring to Message Bus;
- durable retry count and terminal state;
- bounded retry and dead-letter behavior;
- acknowledgement only after terminal persistence;
- exact request/event idempotency;
- provider-capable `paperclaw-team-run` CLI;
- model-call latency/token/retry/cost instrumentation;
- per-run and aggregate observability reports;
- success rate, tool failure rate, P50/P95/P99 latency, token totals, estimated cost, unpriced calls, and failure categories;
- `paperclaw-observe` CLI;
- deterministic tests and opt-in live-provider acceptance;
- Linux/Windows focused and full non-live CI gates.

## Pending

- GitHub Actions results for the exact branch HEAD;
- any fixes required by CI;
- live-provider workflow execution with repository secret;
- final Handoff.

No merge to `main` has been performed.
