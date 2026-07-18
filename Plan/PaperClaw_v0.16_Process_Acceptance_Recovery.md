# PaperClaw v0.16 — Process Acceptance & Recovery

## Goal

Close the largest remaining offline acceptance gaps after the consolidated v0.11-v0.15 PR by exercising the production entry point through real operating-system processes and real HTTP sockets.

## MVP

1. Start a deterministic local OpenAI-compatible provider as a separate process.
2. Start `paperclaw-api` through the real Uvicorn entry point as a separate process.
3. Submit a run over HTTP, consume persisted SSE events, and verify the terminal result.
4. Verify idempotency and `Last-Event-ID` replay through the external HTTP boundary.
5. Kill the service process while a provider request is in flight.
6. Restart the service with the same SQLite database after lease expiry.
7. Verify abandoned-run reconciliation, one-time requeue, and eventual completion.
8. Expose lease, heartbeat, queue-timeout and run-timeout settings on the service CLI so operational tests and deployments can configure them explicitly.

## Non-goals

- external paid-provider credentials;
- distributed exactly-once execution;
- hard interruption of arbitrary synchronous Python code;
- authentication, tenants or RBAC;
- Redis/PostgreSQL implementations;
- DNS-rebinding-safe network sandboxing.

## Acceptance boundary

The provider is a deterministic local HTTP process implementing the OpenAI-compatible chat-completions contract. This proves the network adapter and production Uvicorn path without claiming compatibility with every external gateway.
