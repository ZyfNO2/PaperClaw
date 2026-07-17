# PaperClaw v0.13 Known Limitations

- SQLite is the reference single-host store; PostgreSQL/Redis adapters are not implemented.
- Worker leases rely on an injected wall-clock value and do not provide distributed clock consensus.
- An in-flight Provider HTTP request cannot be reattached after process death.
- Arbitrary shell or child-process state cannot be resumed.
- Automatic replay is allowed only once and only when no action receipt exists.
- Action receipt safety applies only to call paths using `IdempotentActionExecutor` or equivalent integration.
- Pending action receipts deliberately force uncertainty; no automatic compensation is attempted.
- MultiAgent durable mailbox and worker-to-worker recovery are not included.
- Schema migration beyond version 1 is not implemented.
- A real forced process termination and restart smoke remains pending.
- The v0.12 application service is not yet backed by this store.
