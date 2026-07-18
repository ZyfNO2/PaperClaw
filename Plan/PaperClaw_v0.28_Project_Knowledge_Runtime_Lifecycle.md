# PaperClaw v0.28 Project Knowledge Runtime + Lifecycle

> Status: implementation in progress
> Stack base: `feat/v0.27-forgotten-debt-product-foundation @ 95008519a612ab61e552e7099d15d792c0f17752`
> Branch: `feat/v0.28-project-knowledge-runtime`

## Goal

Turn the v0.27 project manifest and deterministic local index into a complete runtime lifecycle without silently trusting stale knowledge.

## Scope

- explicit index policy: `require_current`, `allow_stale`, `disabled`;
- project-scoped memory namespace derived from `project_id`;
- project knowledge lifecycle service with inspect/rebuild/refresh operations;
- bounded polling watcher with explicit start/stop and no implicit background thread;
- hybrid retrieval protocol that can combine BM25 and optional semantic retrievers;
- deterministic reciprocal-rank fusion and citation-preserving deduplication;
- runtime status surfaced through CLI;
- Linux/Windows focused tests and full non-live regression.

## Non-goals

- no hosted embedding provider;
- no hidden network calls;
- no mandatory filesystem watcher;
- no external vector database claim;
- no automatic merge.

## Acceptance

- project memory data is isolated by project ID;
- stale index policy is explicit and tested;
- watcher detects changes and stops cleanly;
- hybrid fusion is deterministic;
- citations remain grounded to source chunks;
- existing non-project workspaces remain compatible;
- full regression remains green.
