# PaperClaw v0.29 Artifact Revisions — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

- Branch: `feat/v0.29-artifact-revisions`
- Draft PR: `#58`
- Stack base: `feat/v0.28-project-knowledge-runtime @ e09678f0111e359296e18ed9881ac2fc9517a278`
- Exact validated implementation SHA: `cc3f656ee2b9d82910913fdd172e557dd5d5307f`
- Validation run: `29661212521`

## Delivered

### Product Artifact contracts

- `ArtifactRecord`
- `ArtifactRevision`
- `ArtifactBundle`
- `ArtifactSourceLinks`
- typed conflict, capacity, integrity and not-found errors

These records are separate from retrieval `SourceArtifact` records.

### Append-only storage

- SQLite artifact/revision/idempotency metadata;
- content-addressed local blobs;
- contiguous per-artifact revision numbers;
- exact create/revise retry returns the original result;
- conflicting idempotency reuse is rejected;
- multiple spawned processes append unique contiguous revisions;
- blob byte length and digest are verified on read.

### Source and metadata policy

- optional Project, Run, Task and Trace identifiers;
- bounded identifiers;
- detached deeply immutable JSON metadata;
- credential-shaped fields rejected;
- content and metadata byte limits.

### Export

- destination-root confinement;
- parent traversal rejected;
- symbolic-link target rejected;
- existing files are not overwritten unless explicitly requested;
- atomic temporary-file replacement.

### CLI

```text
paperclaw artifact --workspace . create
paperclaw artifact --workspace . list
paperclaw artifact --workspace . show
paperclaw artifact --workspace . revise
paperclaw artifact --workspace . export
```

CLI source files must be regular non-symlink files within the selected workspace.

## Validation

```text
implementation SHA: cc3f656ee2b9d82910913fdd172e557dd5d5307f
run: 29661212521
927 passed / 0 failed
10 marker-driven setup skips
artifact: v029-full-regression-29661212521
digest: sha256:5970836ca12a80dc6a61501007d132b53bbdfd2e48e3e240e3cf81f86cea345a
```

Ubuntu and Windows focused gates, multi-process append tests, v0.28 regression slices, full Windows non-live regression and Ruff all passed.

## Known limits

- local file store only;
- no blob garbage collection;
- no public sharing;
- no collaborative editor;
- no automatic HTML/script execution;
- Desktop integration is deferred to v0.30.

## Next stacked line

`feat/v0.30-desktop-product-integration`.

## Final classification

**COMPLETE**

PR remains Draft and unmerged.
