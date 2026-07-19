# PaperClaw v0.30 Post-Review Hardening — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

- Repository: `ZyfNO2/PaperClaw`
- Branch: `fix/v0.30-post-review-hardening`
- Draft PR: `#60`
- Base: `feat/v0.30-desktop-product-integration @ 233bad0a4008f1cce4e7f49dabbed1dbe47cfdfe`
- Exact validated implementation SHA: `0e969c08d27c5453048656b0f7298e89ed59cdfa`
- Validation run: `29686711066`
- Plan: `Plan/PaperClaw_v0.30_Post_Review_Hardening.md`

## Review outcome

The review found and fixed eight substantive issues across filesystem safety, Artifact persistence, Project index integrity, Hybrid retrieval and process lifecycle.

### Workspace confinement

- `.paperclaw` parent symlink redirection is rejected;
- Artifact database/blob/export locations are resolved beneath the selected Workspace;
- Artifact database, blob roots, individual Blob leaves and export roots cannot be symlinks;
- Desktop returns public `artifact_policy_denied` errors;
- CLI rejects redirected storage without creating an external database.

### Atomic filesystem operations

- predictable PID temporary files removed;
- random exclusive temporary files used;
- content is flushed and fsynced before installation;
- `overwrite=False` uses an atomic hard-link no-clobber operation where available;
- the fallback uses `O_CREAT | O_EXCL`;
- concurrent export tests prove one complete winner and one explicit `FileExistsError`.

### Artifact storage

- Artifact and Revision contracts are validated before Blob writes;
- idempotency conflicts are checked before Blob writes;
- target Artifact existence is checked before Revision Blob writes;
- rejected requests create no avoidable orphan Blob;
- exact SQL Artifact count added;
- Desktop recent rows remain bounded;
- Revision detail has a capacity gate;
- portable path validation rejects traversal, empty segments, Windows reserved names, ADS syntax and trailing-dot/space names.

### Project index integrity

Metadata schema is now v2 and includes:

```text
project_id
database
database_sha256
source_fingerprint
file_count
indexed_files
```

The runtime verifies:

- strict metadata fields and types;
- sorted unique file records;
- source fingerprint self-consistency;
- metadata byte and record limits;
- database path identity;
- SQLite database SHA-256;
- source freshness.

A swapped database returns `index_database_mismatch`. `allow_stale` accepts only a valid, database-bound index whose source fingerprint alone has changed. Legacy schema v1 requires rebuild.

### Hybrid retrieval

- finite positive weights required;
- boolean, NaN and infinity weights rejected;
- backend names must be unique;
- duplicate chunk IDs within one backend rejected;
- `HybridCandidateMismatchError` added;
- same chunk ID with different document/version/text/hash/locator identity fails closed;
- same identity with different score/rank continues to fuse deterministically.

### CLI Task lifecycle

- cached process-scoped Task runtimes now have `shutdown_task_runtimes`;
- cache is detached before supervisor shutdown;
- shutdown is idempotent;
- optional store close is supported;
- `atexit` remains a fallback;
- installed CLI entry point always shuts down supervisors in `finally`;
- normal and exceptional CLI exit paths are tested;
- the previous post-pytest `paperclaw-cli-task-worker` traceback is absent from final evidence.

## Validation

Exact implementation SHA:

```text
0e969c08d27c5453048656b0f7298e89ed59cdfa
```

Run:

```text
29686711066
```

Results:

```text
Ubuntu focused: SUCCESS
Windows focused: SUCCESS
Full Windows non-live regression: SUCCESS
Focused Ruff: SUCCESS
Repository Ruff: SUCCESS
```

Focused acceptance on each OS:

```text
149 passed / 0 failed
```

Full regression:

```text
973 passed / 0 failed
10 marker-driven setup skips
5 deselected real/provider tests
1 upstream Starlette/httpx warning
pytest exitstatus: 0
captured process exit code: 0
Exception in thread: absent
```

Artifacts:

```text
v030-review-full-29686711066
sha256:65e58bb38ed6c54a87d0c6ec38905a4bd011c70bfde6694c5ed3a168e105c37a

v030-review-focused-Linux-29686711066
sha256:6c7273d0a732928df6401ecc8b871f42a053e82de153ae95b6c4d03b6521bfec

v030-review-focused-Windows-29686711066
sha256:168599b6eea224f14ac5ebf51df9b20d20f114bb7a39cbbb11abf25a51e459b8
```

## Negative evidence retained

- Initial review CI failed on two real issues: invalid CLI input created SQLite before rejection, and `a//b` was normalized before empty-segment validation.
- A subsequent full run had all pytest calls passing but printed a background CLI worker exception after SessionFinish.
- CI was expanded to preserve stdout/stderr and raw process exit code.
- Both implementation defects were fixed; final output is clean.

## Remaining limits

- Cross-platform APIs cannot completely eliminate a hostile same-user directory-topology swap without platform-specific directory-handle primitives.
- SQLite metadata and content-addressed local files are not a distributed object store.
- Blob garbage collection is still deferred.
- Index schema v1 is intentionally invalidated and must be rebuilt.
- Database digest verification adds local I/O during Project index inspection.

## Stack state

```text
v0.27 PR #56
  ↓
v0.28 PR #57
  ↓
v0.29 PR #58
  ↓
v0.30 PR #59
  ↓
v0.30 post-review hardening PR #60
```

All remain unmerged. PR #60 remains Draft.

## Final classification

**COMPLETE**

No merge, Ready transition or branch deletion was performed.
