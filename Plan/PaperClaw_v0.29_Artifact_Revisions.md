# PaperClaw v0.29 Artifact Revisions

> Status: implementation complete / acceptance complete  
> Stack base: `feat/v0.28-project-knowledge-runtime @ e09678f0111e359296e18ed9881ac2fc9517a278`  
> Branch: `feat/v0.29-artifact-revisions`  
> Draft PR: `#58`  
> Validated implementation SHA: `cc3f656ee2b9d82910913fdd172e557dd5d5307f`

## Goal

Introduce first-class append-only product artifacts, separate from chat messages and retrieval source records.

## Delivered

- stable Artifact ID and type;
- immutable contiguous revisions;
- content-addressed SHA-256 blobs;
- Run, Task, Trace and Project source links;
- bounded content and deeply immutable metadata;
- idempotent create/revise with conflict detection;
- deterministic list/show/read/export;
- root-bounded export with no overwrite by default;
- CLI create/list/show/revise/export;
- Linux and Windows multi-process append evidence.

## Storage

```text
.paperclaw/artifacts/
  artifacts.sqlite3
  blobs/sha256/<prefix>/<content_hash>
```

Metadata is stored in SQLite. Blob content is verified by byte length and SHA-256 whenever it is read.

## Invariants

- existing revisions are never modified;
- revision numbers stay contiguous;
- concurrent processes cannot allocate the same number;
- metadata is detached and immutable;
- credential-shaped metadata fields are rejected;
- exact retries return the existing result;
- conflicting idempotency reuse fails closed;
- CLI source files remain inside the workspace and cannot be symbolic links;
- export cannot escape the destination root.

## CLI

```text
paperclaw artifact --workspace . create ...
paperclaw artifact --workspace . list
paperclaw artifact --workspace . show <artifact_id>
paperclaw artifact --workspace . revise <artifact_id> ...
paperclaw artifact --workspace . export <artifact_id> ...
```

## Validation

```text
implementation SHA: cc3f656ee2b9d82910913fdd172e557dd5d5307f
run: 29661212521
927 passed / 0 failed
10 marker-driven setup skips
artifact: v029-full-regression-29661212521
digest: sha256:5970836ca12a80dc6a61501007d132b53bbdfd2e48e3e240e3cf81f86cea345a
```

Ubuntu and Windows focused gates, v0.28 regression slices, full Windows non-live regression and Ruff all passed.

## Limits

- no public sharing service;
- no collaborative editor;
- no arbitrary HTML execution;
- no cloud object store claim;
- no blob garbage collector in this release;
- no automatic merge.

## Next

`v0.30 Desktop Product Integration` adds bounded desktop access to capabilities, project status and artifacts.

## Final classification

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

PR #58 remains Draft and unmerged.
