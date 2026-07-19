# PaperClaw v0.30 Post-Review Hardening

> Status: implementation in progress  
> Base: `feat/v0.30-desktop-product-integration @ 233bad0a4008f1cce4e7f49dabbed1dbe47cfdfe`  
> Branch: `fix/v0.30-post-review-hardening`

## Review findings

1. Desktop and CLI Artifact roots checked only leaf symlinks. A workspace-local `.paperclaw` symlink could redirect persistence outside the selected workspace.
2. Project manifest/index metadata and Artifact export used predictable PID temporary names. A pre-created symlink could redirect writes; same-process concurrent exports also shared one temporary path.
3. `overwrite=False` export used check-then-`os.replace`, so concurrent writers could still overwrite one another.
4. Desktop overview loaded up to 5,000 Artifact rows to compute a count and silently under-counted larger stores; Artifact detail loaded the full revision history before applying its display cap.
5. Artifact Blob persistence occurred before idempotency conflict/existence checks, allowing invalid or conflicting requests to leave avoidable orphan blobs.
6. Project stale-index metadata was not cryptographically bound to the SQLite database file. A swapped database could still be accepted under `allow_stale` when metadata was otherwise parseable.
7. Hybrid RRF accepted non-finite weights and silently fused the same `chunk_id` even when citation-bound content differed across backends.

## Required fixes

- enforce workspace confinement on the resolved Artifact storage path;
- reject Artifact database/blob symlink leaves;
- use exclusive random temporary files;
- implement atomic no-clobber export for `overwrite=False`;
- add `count_artifacts` and bounded `get_bundle` reads;
- move Blob persistence after validation/idempotency/existence checks;
- bind Project metadata schema v2 to the database SHA-256;
- reject symlinked index database/metadata and oversized metadata;
- require finite positive Hybrid weights;
- fail closed on conflicting citation identity for a shared chunk ID;
- add Linux/Windows focused, concurrency, security and full-regression evidence.

## Non-goals

- no merge or Ready transition;
- no distributed object store;
- no external vector provider;
- no Artifact garbage collector;
- no Desktop framework rewrite.
