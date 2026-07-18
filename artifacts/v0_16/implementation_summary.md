# PaperClaw v0.16 Implementation Summary

## Delivered

- operational CLI controls for durable worker lease and heartbeat timing;
- operational CLI controls for queue timeout and whole-run timeout;
- a deterministic OpenAI-compatible provider implemented as a separate HTTP process;
- a real `paperclaw-api` Uvicorn subprocess acceptance path;
- external HTTP run submission and terminal-state polling;
- persisted SSE replay and `Last-Event-ID` resume verification;
- request idempotency verification through the public HTTP boundary;
- service process kill during an in-flight Provider request;
- restart against the same SQLite database after worker-lease expiry;
- verification that the original durable run ID is reconciled, requeued once and completed;
- dedicated stacked-PR CI for process acceptance, Windows regression and Ruff.

## Architecture decision

The acceptance Provider is deliberately local and deterministic, but it communicates only through the same OpenAI-compatible HTTP contract used by production adapters. The service is launched through the installed module entry point and real Uvicorn server, not an in-process ASGI test client.

## Evidence intent

The process-kill test proves that SQLite state, transitions, public events and worker leases survive operating-system process death. It does not claim restoration of an in-flight TCP response; the abandoned execution is reconciled and safely retried after lease expiry.
