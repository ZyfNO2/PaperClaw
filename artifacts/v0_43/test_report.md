# v0.43 Test Report

Date: 2026-07-27

## Automated

- focused Academic/Service/Desktop/Capability: `20 passed`
- full offline regression: `1030 passed, 27 skipped, 8 deselected`
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
