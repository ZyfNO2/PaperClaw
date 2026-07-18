# PaperClaw v0.15 Known Limitations

- v0.15 is a single-host SQLite reference implementation, not a distributed worker system.
- The v0.15 branch is stacked on unmerged PR #37 and must not be merged to `main` before its parent is integrated.
- The PR currently targets `main` only to run the existing pull-request workflows; it should be retargeted or rebased after #37 lands.
- Queue and whole-run timeouts are enforced. Provider-call and tool-call timeout values are typed contracts but still require boundary-specific adapters for hard enforcement.
- Cooperative cancellation cannot interrupt arbitrary Python code that ignores the stop token.
- An in-flight Provider HTTP response cannot be reattached after process death.
- Arbitrary child-process instruction state cannot be restored after process death.
- Cross-process tests expire a worker lease and reconcile in a second Python process; they are not a manual kill of a real Provider/tool execution.
- SQLite event polling is adequate for the MVP but is not a high-scale notification system.
- The default service policy denies Bash and unknown tools unless they receive trusted static approval. CLI and Desktop composition remain separate.
- URL checks reject literal private and metadata hosts. DNS rebinding and post-resolution egress controls require a network-egress adapter.
- Workspace checks validate path containment but do not replace operating-system sandboxing.
- Full authentication, tenant ownership checks, RBAC, quota accounting and audit retention are not implemented.
- Redis Streams, PostgreSQL, circuit breaker, fallback-model and telemetry exporters are documented plugin boundaries, not delivered plugins.
- `cancel_on_disconnect` depends on the ASGI server surfacing disconnect state; manual browser/proxy acceptance remains pending.
- Exactly-once external side effects are not claimed. Tools need durable action receipts and external idempotency support for stronger guarantees.
