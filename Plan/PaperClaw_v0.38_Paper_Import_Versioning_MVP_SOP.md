# PaperClaw v0.38 — Paper Import & Versioning MVP SOP

## Objective

Deliver one user-visible loop: import PDF/Markdown/TXT into a project-managed store,
preserve immutable versions, inspect candidate metadata, and explicitly confirm it
through Python, REST, CLI or Desktop.

## Existing implementation reference

| Reference | Required paths | Borrowed idea | Do not copy |
|---|---|---|---|
| PaperClaw v0.29 | `src/paperclaw/artifacts/store.py` | content addressing, integrity, append-only history | Artifact tables as PaperRecord |
| PaperClaw retrieval | `src/paperclaw/retrieval/incremental.py`, `contracts.py` | stable identity/version/locator seam | indexing during import |
| Draftpaper-loop | `docs/DPL_SCHEMA.md`, `draftpaper_cli/loop_contract.py` | evidence identity and provenance | paper-generation workflow or branded code |

Implementation used PaperClaw's existing safety and versioning concepts; no external
source code was copied. Reference repository commits must be refreshed before any
future substantial migration.

## Phase gates

- [x] Phase 1: managed import, hash idempotency, explicit version append, replay and metadata confirmation.
- [x] Phase 2: Python, REST and CLI share one domain service and safe public projection.
- [x] Phase 3: Desktop picker/library/detail/version/confirmation bridge and local corpus smoke.

## Hard acceptance

- [x] PDF, Markdown and UTF-8 TXT accepted; unsupported/corrupt inputs fail closed.
- [x] Source removal does not break managed replay.
- [x] Repeated hash is idempotent; explicit changed content appends a version.
- [x] Metadata confirmation uses optimistic concurrency.
- [x] REST confines sources to configured roots and does not expose managed paths.
- [x] Focused tests, lint, package build and non-live regression recorded.
- [ ] Native Windows Desktop click-through demonstration recorded.

## Non-goals

Structured academic parsing, retrieval mutation, LaTeX projects, remote metadata,
batch queues, attachments, version deletion and verified bibliographic claims.
