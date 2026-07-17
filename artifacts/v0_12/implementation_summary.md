# PaperClaw v0.12 Service API Implementation Summary

## Status

**IMPLEMENTED / OFFLINE VALIDATED**

Implementation verification head: `1a225ce5aa5ebcc53729607fda19834cd50e5adf`.

## Delivered

- Optional `service` dependency group with FastAPI and Uvicorn.
- `paperclaw api` and `paperclaw-api` entrypoints.
- `RunApplicationService` wrapping the existing synchronous `QueryEngine` in a bounded worker pool.
- Typed request, run-view, event and public-error contracts.
- Process-local active-run limit.
- Request-digest idempotency with conflict rejection.
- Cooperative cancellation through the existing QueryEngine stop path.
- Bounded replayable event retention and `Last-Event-ID` SSE resume.
- Secret-like field removal before HTTP/plugin projection.
- Environment-backed production Runtime factory.
- Static service observer plugin registry with failure isolation.
- Unit and FastAPI/TestClient integration tests.

## Architecture decision

The HTTP layer is an optional adapter. Routes do not execute tools, construct prompts, or redefine Runtime lifecycle semantics. The existing `QueryEngine`, `AgentRuntimeExecutor`, event bridge and verification flow remain authoritative.

## Verification

- Repository-wide Windows non-live pytest: `706 passed` on workflow run `29614255414`.
- Ruff correctness gate: PASS on workflow run `29614255414`.
- Existing Desktop focused tests and PyInstaller packaging remained green on the preceding implementation run.

## Not claimed

- Production deployment.
- Authentication/authorization policy.
- Distributed idempotency or workers.
- Real Provider HTTP-service smoke.
- Durable service restart recovery; v0.13 provides the persistence primitives separately.
