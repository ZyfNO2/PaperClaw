# v0.43 Test Report

Date: 2026-07-27

## Automated

- focused Academic/Service/Desktop/Capability before review: `20 passed`
- post-review Academic/Service/Desktop regression: `18 passed`
- final full offline regression: `1032 passed, 27 skipped, 8 deselected`
- targeted Ruff: passed
- package build: `paperclaw-0.43.0.tar.gz` and wheel succeeded

## Live

- ColQwen2 CUDA/bfloat16 single-page smoke: passed
- compatible runtime: colpali-engine 0.3.10 / Transformers 4.51.3

## Excluded

Five live-provider failures observed when the inherited `PAPERCLAW_API_KEY` returned
HTTP 401. They are unrelated to Academic RAG and are not counted as offline regression
failures. The clean offline run explicitly removed provider variables.

Native Desktop and frozen 107-paper corpus acceptance remain pending by user request.

## PaperAgent synchronization follow-up

- canonical `exact` identifier channel: added and regression-tested
- PaperAgent structural adapter contract: passed on Python 3.11 and 3.12
- real generated PDF cross-repository tracer:
  PaperClaw ingest/parse/index/retrieve/resolve → PaperAgent evidence ledger: passed
- PaperClaw append-only Artifact draft/approve/final adapter: passed
- full PaperClaw offline regression after synchronization: `1032 passed, 23 skipped,
  15 deselected`
- PaperClaw wheel contains the PEP 561 `paperclaw/py.typed` marker
- frozen local corpus report: 107 entries, digest
  `57ef613aa18f060e0ef9d683436d32f2b0c08e68127011403e81c76e2a4ca816`
- parser outcomes after bbox/render hardening: 90 `ready`, 7 explicit `partial`,
  10 `failed` invalid/corrupt inputs
- valid-paper index: 45,281 objects, state `ready`; exact identifier smoke:
  `sufficient`, top exact score `1.0`
- private source PDFs remain untracked; the committed report contains no full text

The Native Desktop, real LLM, blinded quality labels, and human approval release
gate remains pending and is not represented as completed by these offline tests.
