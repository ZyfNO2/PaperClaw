# PaperClaw v0.30 Post-Review Hardening

> Status: implementation complete / acceptance complete  
> Base: `feat/v0.30-desktop-product-integration @ 233bad0a4008f1cce4e7f49dabbed1dbe47cfdfe`  
> Branch: `fix/v0.30-post-review-hardening`  
> Draft PR: `#60`  
> Validated implementation SHA: `0e969c08d27c5453048656b0f7298e89ed59cdfa`

## Review scope

The review covered the v0.28-v0.30 stacked product line, with emphasis on:

- workspace and symlink confinement;
- append-only Artifact storage and export races;
- idempotency ordering and orphan side effects;
- Project index freshness and integrity;
- Hybrid retrieval identity preservation;
- Desktop/CLI public boundaries;
- process-scoped background-task lifecycle;
- cross-platform CI evidence and failure visibility.

## Findings and fixes

### 1. Parent-symlink workspace escape

**Finding:** Desktop and CLI checked only Artifact leaf paths. A workspace-local `.paperclaw` symlink could redirect the Artifact database, blobs or exports outside the selected workspace.

**Fix:**

- added `resolve_confined_path`;
- resolved every existing parent symlink before persistence;
- added explicit `confinement_root` to `FileArtifactStore`;
- rejected symlinked Artifact roots, database files, blob directories and export roots;
- applied the same policy to Desktop and Artifact CLI entry points.

### 2. Predictable temporary files

**Finding:** Project manifest/index metadata and Artifact export used predictable PID-based temporary names. Pre-created symlinks and same-process concurrent operations could collide with those names.

**Fix:**

- introduced exclusive random temporary files via `tempfile.mkstemp`;
- flush and `fsync` content before installation;
- re-check confinement before final installation;
- clean temporary files on all normal exception paths.

### 3. Non-overwrite export race

**Finding:** `overwrite=False` performed a check followed by `os.replace`, so two concurrent writers could both pass the check and one could overwrite the other.

**Fix:**

- use atomic hard-link installation when supported;
- use `O_CREAT | O_EXCL` as the cross-platform no-clobber fallback;
- concurrent acceptance proves exactly one writer succeeds and the winner is complete.

### 4. Artifact query bounds and incorrect overview count

**Finding:** Desktop loaded up to 5,000 Artifact rows to compute a count and could silently under-count larger stores. Artifact detail loaded the complete revision history before enforcing its display limit.

**Fix:**

- added SQL `COUNT(*)` through `count_artifacts`;
- kept recent-list retrieval separately bounded;
- added `get_bundle(max_revisions=...)` capacity enforcement;
- Desktop returns `artifact_too_large` instead of serializing an oversized revision history;
- public response remains capped at 1 MiB.

### 5. Avoidable orphan Blob writes

**Finding:** Blob persistence happened before request validation, idempotency conflict checks and Artifact existence checks. Invalid or conflicting requests could leave unreferenced content-addressed files.

**Fix:**

- validate Artifact/Revision contracts first;
- inspect idempotency before Blob mutation;
- verify target Artifact existence before Revision Blob creation;
- retain hash verification for exact idempotent retries;
- tests prove rejected invalid/conflicting requests create no new Blob.

### 6. Project index database was not bound to metadata

**Finding:** `allow_stale` trusted structurally valid metadata and source fingerprint, but metadata did not authenticate the SQLite index bytes. A replaced database could be accepted as stale.

**Fix:**

- upgraded Project index metadata to schema v2;
- record and verify `database_sha256`;
- validate metadata field set, types, file count, ordering and source-fingerprint self-consistency;
- cap metadata at 1 MiB and indexed file records at 100,000;
- reject database/metadata symlinks;
- database replacement now returns `index_database_mismatch` and is never accepted by `allow_stale`;
- schema v1 requires an explicit rebuild.

### 7. Hybrid RRF accepted invalid configuration and citation conflicts

**Finding:** Hybrid retrieval accepted `NaN`, infinity and boolean weights. It also silently fused identical `chunk_id` values even when backends disagreed on citation-bound content or locator identity.

**Fix:**

- require finite positive numeric weights;
- reject boolean weights and invalid RRF constants;
- reject duplicate backend names;
- reject duplicate `chunk_id` values inside a backend;
- add `HybridCandidateMismatchError`;
- fail closed when document/version/text/hash/locator identity differs for the same chunk ID;
- preserve legitimate fusion when only backend rank/score differs.

### 8. CLI Task Supervisor outlived the CLI process lifecycle

**Finding:** Full regression passed but stdout ended with `Exception in thread paperclaw-cli-task-worker`. Process-scoped runtimes were cached and their daemon supervisors had no deterministic shutdown before interpreter finalization.

**Fix:**

- added idempotent `shutdown_task_runtimes`;
- clear the cache before stopping supervisors;
- stop cached supervisors and optional stores at process exit;
- register an `atexit` fallback;
- more importantly, call shutdown in the installed CLI entry point `finally` block while Python and asyncio executors remain fully operational;
- tests cover normal CLI return, exceptional CLI exit, cache recreation and repeated shutdown;
- final full stdout contains no `Exception in thread` output.

## New shared primitive

```text
src/paperclaw/storage_safety.py
```

It provides:

- `resolve_confined_path`;
- `atomic_write_bytes`;
- exclusive random temporary files;
- atomic overwrite;
- atomic/best-available no-clobber installation;
- optional root confinement.

## Validation

Exact implementation SHA:

```text
0e969c08d27c5453048656b0f7298e89ed59cdfa
```

GitHub Actions run:

```text
29686711066
```

Results:

- Ubuntu reviewed focused acceptance: SUCCESS;
- Windows reviewed focused acceptance: SUCCESS;
- full Windows non-live repository regression: SUCCESS;
- focused correctness Ruff: SUCCESS;
- repository correctness Ruff: SUCCESS.

Focused acceptance, on each platform:

```text
149 passed / 0 failed
```

Full machine-readable regression:

```text
973 passed / 0 failed
10 marker-driven setup skips
5 deselected real/provider tests
1 upstream Starlette/httpx deprecation warning
pytest SessionFinish exitstatus: 0
captured process exit code: 0
background thread exception text: absent
```

Evidence artifacts:

```text
full:
  v030-review-full-29686711066
  sha256:65e58bb38ed6c54a87d0c6ec38905a4bd011c70bfde6694c5ed3a168e105c37a

Linux focused:
  sha256:6c7273d0a732928df6401ecc8b871f42a053e82de153ae95b6c4d03b6521bfec

Windows focused:
  sha256:168599b6eea224f14ac5ebf51df9b20d20f114bb7a39cbbb11abf25a51e459b8
```

## Preserved negative evidence

The review did not discard failing evidence:

1. Initial focused/full runs exposed CLI database creation before source-file validation and collapsed empty path segments such as `a//b`; both implementations were corrected without weakening tests.
2. A later full run had 969 passing calls and pytest exitstatus 0 but exposed a post-session `paperclaw-cli-task-worker` exception; CI was extended to retain stdout/stderr and the raw process exit code, then the runtime lifecycle was fixed.
3. The final run contains 973 passing calls, exit code 0 and no background thread traceback.

## Remaining limitations

- The implementation uses cross-platform `pathlib`/filesystem APIs rather than platform-specific directory-handle operations such as Linux `openat`; an attacker able to mutate directory topology concurrently retains a narrow same-user TOCTOU window.
- The local SQLite/Blob implementation is not a distributed object store and does not provide Blob garbage collection.
- Project index schema v1 is intentionally not trusted after this hardening and must be rebuilt.
- Database hashing increases index inspection cost in exchange for fail-closed integrity.
- No external vector provider, Artifact sharing service or Desktop framework rewrite is included.

## Final classification

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

PR #60 remains Draft and unmerged. No branch was deleted.
