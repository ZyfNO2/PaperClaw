# Changelog

All notable PaperClaw changes are recorded here. Versions are developed on isolated
branches and are intended to be squash-merged so one released version contributes
one commit to `main`.

## [0.32.0] — Unreleased

### Added

- durable Team Run to SessionEvent/Trace projection;
- stable Team Run identity derived from the idempotent request id;
- trace-aware model usage collection with provider/model, latency, retries, tokens and cost;
- bounded Tool lifecycle projection without copying arguments or output;
- `paperclaw-team-run --trace-database`;
- `paperclaw-observe --request-id`;
- Linux/Windows closure tests, package build smoke and opt-in live-provider acceptance.

### Changed

- package version updated from `0.0.1` to `0.32.0`;
- Team Run output now includes the durable trace `run_id` and database path;
- the Team Run CLI composes the existing Coordinator with observed Workers;
- README and capability maturity records are aligned with v0.31/v0.32 reality.

### Known limits

- projection and choreography state are not yet one atomic Outbox transaction;
- delivery is at-least-once with idempotent event boundaries;
- SQLite remains a same-filesystem reference backend;
- cancellation and systematic failure injection are deferred to v0.33.

## [0.31.0] — 2026-07-20

### Added

- provider-capable bus-driven MultiAgent execution;
- durable retry, terminal state and DLQ choreography;
- aggregate latency, reliability, token and cost evaluation;
- operator-supplied exact-match pricing;
- real Mistral acceptance and full non-live repository regression evidence.
