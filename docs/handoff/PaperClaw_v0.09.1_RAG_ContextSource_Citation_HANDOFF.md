# PaperClaw v0.09.1 RAG ContextSource / Citation — Handoff

## Status

- branch: `feat/v0.09.1-rag-contextsource-citation`;
- stacked base: BM25 / Incremental Retrieval PR #24;
- additional dependency: Shared ContextSource Registry PR #25;
- implementation: complete;
- repository CI: pending;
- merge: not requested and not performed.

## Delivered

- Retrieval ContextSource;
- task query extraction and stopword filtering;
- Context budget/trust integration;
- CitationAnchor;
- defensive duplicate/stale boundary;
- no-answer / abstention decision and pinned local constraint;
- Citation Correctness;
- Unsupported Claim Rate;
- Abstention Accuracy;
- prompt injection fixture;
- deterministic offline RAG demo.

## Invariants

1. Retrieval evidence is always `external_untrusted`.
2. CitationAnchor binds the exact active Version and locator.
3. Only candidates selected into the final assembly may be cited.
4. Missing or broken evidence produces an abstention constraint rather than fabricated evidence.
5. Document instructions never enter the Runtime protocol section.
6. RAG code never invokes PromptAssembler or a Provider.
7. ContextOrchestrator remains the only budget/trust/section authority.
8. PR #24 remains the authoritative stale and exact-duplicate retrieval layer.
9. Unknown citation IDs are incorrect citations.
10. Offline metrics use explicit support labels and do not claim semantic-model evaluation.

## Main files

```text
src/paperclaw/retrieval/context_source.py
src/paperclaw/retrieval/grounding.py
src/paperclaw/retrieval/__init__.py
scripts/run_v0_09_1_rag_demo.py

tests/unit/test_rag_contextsource_grounding.py
tests/integration/test_v0_09_1_rag_demo.py
tests/fixtures/rag_grounding_fixture.json
```

## Dependency handling

Keep the PR Draft while PR #24 and PR #25 are unmerged. After both merge, rebase onto `main`, remove duplicated dependency commits, regenerate the demo artifact, rerun full pytest/Ruff, then consider Ready for Review.

## Verification

Automated tests, fixture and demo script are committed. Exact Actions evidence remains pending because workflow status endpoints currently return upstream 502 through the connector. No Repository GO claim is made until the final branch HEAD passes.
