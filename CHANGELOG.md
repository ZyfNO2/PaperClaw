# Changelog

All notable PaperClaw changes are recorded here. Versions are developed on isolated
branches and are intended to be squash-merged so one released version contributes
one commit to `main`.

## [0.35.0] — Unreleased

### Added

- persistent SQLite hashing-vector retrieval with encoder and corpus fingerprints;
- bounded atomic replace/upsert and deterministic cosine ranking;
- named retrieval backend adapters and explicit weighted-RRF configuration;
- evidence-aware reranking that preserves citation hashes, versions and locators;
- benchmark and observation contracts for research-quality evaluation;
- Recall@5/10, MRR, nDCG@10 and document Recall@10;
- citation precision/recall, grounded-claim rate, claim coverage and abstention accuracy;
- latency, token, estimated-cost and baseline-delta reporting;
- `paperclaw-retrieval-quality` CLI and deterministic example fixtures;
- Linux/Windows focused tests, package smoke and full non-live regression gate.

### Changed

- package version updated to `0.35.0`;
- `HybridRetriever` supports both the original tuple API and named adapters;
- semantic persistence uses the canonical version-bound `ChunkLocator` contract;
- version workflows are scoped to their own development branches.

### Known limits

- local vectors use deterministic feature hashing, not transformer embeddings;
- no hosted embedding service or external vector database is bundled;
- groundedness uses explicit benchmark support labels, not model self-grading;
- benchmark conclusions depend on the quality of curated relevance and claim labels.

## [0.34.0] — Unreleased

### Added

- real Redis Streams `MessageBusStore` backend;
- Lua-atomic sequence allocation, capacity check, exact idempotency and Stream append;
- Consumer Group delivery, Pending Entry recovery through `XAUTOCLAIM`, and direct-recipient filtering;
- contiguous logical Ack cursor across out-of-order process completion;
- PostgreSQL attempt, terminal snapshot and ordered-Outbox store;
- `FOR UPDATE SKIP LOCKED` Outbox claim and stale claim takeover;
- Team Run and Team Cancel CLI selectors for SQLite/Redis and SQLite/PostgreSQL;
- `distributed` package extra with Redis and psycopg;
- real Redis 7 + PostgreSQL 16 integration acceptance;
- two-process shared-consumer acceptance without duplicate terminal results.

### Changed

- package version updated to `0.34.0`;
- distributed backends implement the same runtime protocols used by SQLite;
- Capability Catalog adds `multiagent.distributed_runtime [shipped]`.

### Known limits

- Redis Cluster cross-slot Lua deployment is not claimed;
- PostgreSQL and Redis do not form one distributed transaction;
- Trace projection remains the local SQLite reference store;
- external Tool side effects still require Tool-level idempotency;
- no Kafka or NATS adapter is included.

## [0.33.0] — Unreleased

### Added

- terminal state, terminal snapshot and terminal-event Outbox in one SQLite transaction;
- restart recovery that flushes pending Outbox rows before acknowledging requests;
- exact-idempotent recovery for publish-before-delivered-mark crashes;
- deterministic crash checkpoints for attempt, Coordinator, terminal, publish and Ack windows;
- durable `multiagent.team.cancellations.v1` requests;
- `paperclaw-team-cancel` CLI;
- retryable, permanent and unknown failure disposition;
- immediate DLQ for permanent failures and bounded retry for retryable/unknown failures;
- live Mistral terminal-commit crash recovery acceptance.

### Changed

- package version updated to `0.33.0`;
- `paperclaw-team-run` now uses `ResilientBusDrivenTeamRuntime`;
- terminal metrics, terminal result and DLQ publication use the Outbox path;
- v0.33 capability maturity is represented by `multiagent.resilient_choreography`.

## [0.32.0] — Unreleased

### Added

- durable Team Run to SessionEvent/Trace projection;
- stable Team Run identity derived from the idempotent request id;
- trace-aware model usage collection with provider/model, latency, retries, tokens and cost;
- bounded Tool lifecycle projection without copying arguments or output;
- `paperclaw-team-run --trace-database`;
- `paperclaw-observe --request-id`;
- Linux/Windows closure tests, package build smoke and live-provider acceptance.

### Changed

- package version updated from `0.0.1` to `0.32.0`;
- Team Run output includes the durable trace `run_id` and database path;
- the Team Run CLI composes the existing Coordinator with observed Workers;
- README and capability maturity records align with v0.31/v0.32 reality.

## [0.31.0] — 2026-07-20

### Added

- provider-capable bus-driven MultiAgent execution;
- durable retry, terminal state and DLQ choreography;
- aggregate latency, reliability, token and cost evaluation;
- operator-supplied exact-match pricing;
- real Mistral acceptance and full non-live repository regression evidence.
