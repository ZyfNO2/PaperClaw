# PaperClaw v0.16 Known Limitations

- The acceptance Provider is local and deterministic; no external paid Provider credential is used.
- The test proves real HTTP and Uvicorn behavior, not compatibility with every OpenAI-compatible gateway.
- Killing the service abandons the in-flight Provider request; the response is not reattached after restart.
- Recovery is at-least-once for work without a durable external action receipt. The test deliberately uses a side-effect-free model response.
- Provider and tool timeout values remain cooperative or adapter-bounded; arbitrary synchronous Python code cannot be forcibly interrupted safely.
- SQLite remains the single-host source of truth.
- Authentication, tenant ownership, RBAC, quotas and audit retention are not implemented.
- Redis Streams, PostgreSQL and distributed workers are not implemented.
- DNS rebinding protection and operating-system network/process sandboxing are not implemented.
- The PR is stacked on #40 and must be retargeted or rebased after #40 is merged.
