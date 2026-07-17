# PaperClaw v0.12 Known Limitations

- Service run state and idempotency records are process-local in v0.12.
- The active-run limit is global to one process, not distributed by tenant.
- SSE retains a bounded in-memory history; it is not a durable event subscription log.
- Slow-consumer queue separation is represented by bounded retention rather than a distributed cursor store.
- Plugin hooks are fail-isolated but execute in-process; untrusted dynamic plugin loading is not supported.
- Provider token streaming is not implemented.
- HTTP authentication, authorization, quotas and billing policy are deliberately outside the MVP.
- Client disconnect does not cancel a run; cancellation is explicit.
- A real Uvicorn + Provider + long-running tool smoke remains pending.
- v0.13 durability is not yet wired into `RunApplicationService`; the modules are independently tested reference components.
