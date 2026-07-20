# Changelog

All notable PaperClaw changes are recorded here. Versions are developed on isolated
branches and are intended to be squash-merged so one released version contributes
one commit to `main`.

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

### Known limits

- Outbox atomicity is local to the choreography SQLite database, not an external broker;
- live progress events remain direct best-effort publications;
- external Tool side effects still require Tool-level idempotency;
- PostgreSQL and Redis Streams are deferred to v0.34.

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
