# PaperClaw v0.14 Test Report

## Automated evidence

Exact implementation head: `1a225ce5aa5ebcc53729607fda19834cd50e5adf`.

- Full Windows non-live pytest: `706 passed`, `0 failed`.
- Workflow: `CI`, run `29614255414`.
- Ruff: PASS.
- Pytest artifact ID: `8419962391`.
- Artifact digest: `sha256:68e62ef1f89308cdc116cf7cd948d8a6c5765a01b52f6b2111e59c00ddbce499`.

## Focused evaluation coverage

- dataset load and deterministic digest;
- duplicate-case rejection;
- secret removal from recorded result metadata;
- known Recall@K, MRR, claim and citation values;
- metric plugin success and failure isolation;
- missing recorded case preserved as a failed case;
- JSON and Markdown report output;
- multi-report comparison output;
- canonical generator byte reproducibility across two independent output directories;
- exact canonical dataset and report digests.

## Canonical digests

- Dataset: `a0156e6d5c73ebde49b753b35ebc3337900897ab0f2c6f16b1e9cfcd94e8d774`.
- Report: `68a82cc177bbe465515c11e727b9b351469f365de1a31d7e3972f4e0c5bbdbbc`.

## Classification

The canonical measurements use committed deterministic fixtures and recorded results. They do not represent a live Provider, live GitHub MCP call, or production-repository benchmark.
