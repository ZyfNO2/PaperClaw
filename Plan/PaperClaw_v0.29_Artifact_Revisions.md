# PaperClaw v0.29 Artifact Revisions

> Status: implementation in progress
> Stack base: `feat/v0.28-project-knowledge-runtime @ e09678f0111e359296e18ed9881ac2fc9517a278`
> Branch: `feat/v0.29-artifact-revisions`

## Goal

Introduce first-class, append-only product artifacts separate from chat messages and RAG source artifacts.

## Scope

- stable Artifact ID and type;
- immutable numbered revisions;
- content-addressed blob storage;
- Run / Task / Trace / Project source linkage;
- bounded metadata and content;
- deterministic list/show/read/export APIs;
- idempotent creation and revision append;
- conflict rejection for reused idempotency keys with different content;
- safe workspace export without overwriting by default;
- CLI create/list/show/revise/export;
- Linux/Windows focused and full regression evidence.

## Non-goals

- no public sharing service;
- no collaborative editor;
- no arbitrary HTML execution;
- no cloud object store claim;
- no automatic merge.

## Invariants

- revisions are append-only and never mutated;
- revision numbers are contiguous per artifact;
- blob hash must match stored bytes;
- source links are bounded identifiers only;
- secrets are rejected from metadata;
- export cannot escape the selected destination root;
- duplicate exact requests return the existing object;
- conflicting idempotency reuse fails closed.
