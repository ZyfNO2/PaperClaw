# PaperClaw v0.13 Test Report

## Automated evidence

Exact implementation head: `1a225ce5aa5ebcc53729607fda19834cd50e5adf`.

- Full Windows non-live pytest: `706 passed`, `0 failed`.
- Workflow: `CI`, run `29614255414`.
- Ruff: PASS.
- Pytest artifact ID: `8419962391`.
- Artifact digest: `sha256:68e62ef1f89308cdc116cf7cd948d8a6c5765a01b52f6b2111e59c00ddbce499`.

## Focused durability scenarios

1. Durable run creation and idempotency lookup.
2. Secret-like metadata removal before SQLite persistence.
3. Legal transition and stale CAS rejection.
4. Two workers race to claim one queued run; exactly one succeeds.
5. Lease renewal validates worker identity and run version.
6. Expired run with no action receipt requeues once.
7. A second interrupted attempt becomes `recovery_required`.
8. Existing uncertain action receipt forces manual recovery.
9. Duplicate delivery through `IdempotentActionExecutor` executes the side effect once.
10. Recovery policy plugin exception fails closed.
11. Repeated reconciliation is idempotent after terminal/manual classification.

## Classification

These tests use real SQLite files, separate connections and real threads. They are not a real operating-system process-kill/restart test and do not prove distributed database semantics.
