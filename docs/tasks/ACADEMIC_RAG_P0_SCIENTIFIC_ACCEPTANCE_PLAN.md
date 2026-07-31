# Academic RAG P0 Scientific Acceptance Plan

- Protocol version: `academic-rag-p0-scientific-acceptance.v1`
- Starting exact commit pair: PaperAgent `8aca0c14e21107bd02b802254a24bb8618efab29`; PaperClaw `84c431da9d1dafecb9a8dfa27b3698d609f9542f`.
- `academic.v1` schema SHA-256: `62c3c6bbde000023a95025fdcae53c777fac479ddc9da02a63ea293b0855d2e0`.
- `academic.v1` golden fixture SHA-256: `5f8b3b999de2139c6e328966086043663a3012a068636061971926b979ea647d`.
- Corpus manifest: PaperClaw `benchmarks/academic_rag/v1/corpus_manifest.jsonl`, SHA-256 `389be651cc8ca001f0d8cf2a5be3343ba7764407bc0f4669d620b37c5135ea20`, frozen set `academic-rag-h0-v1`, 12 metadata-only real-paper entries.

## Scope and frozen inputs

The formal pack is owned by PaperClaw at `benchmarks/academic_rag/v1/eval/` and is consumed by PaperAgent scoring. It contains the 32-ID blinded scaffold, question manifest, private gold-label path, labeling guide, reviewer form, and eight-Artifact manifest. The current scaffold is intentionally blocked because its question text is `HUMAN_AUTHOR_REQUIRED`; it is not scientific evidence.

Only user-owned or clearly licensed local papers may enter the controlled corpus. Git may contain metadata, source, license basis, file hash, page count, import/parse state, inclusion state, and exclusion reason. Private PDFs, uncertain-license files, caches, indexes, model weights, databases, raw private LLM payloads, and reviewer-sensitive identity data stay outside Git.

## Blind and label rules

The runner reads only `questions.blinded.jsonl`. It must not receive the private gold path, gold content, accepted answers, locators, or reviewer notes. Gold is loaded only after the run is sealed. Exactly 32 unique question IDs are required, with 8 text, 8 figure, 8 table, and 8 equation questions. A human annotator and an independent reviewer must record accepted answers, supporting paper/version, canonical locator, allowable inference, overclaim boundary, abstention target, severe-error conditions, identities, timestamp, and disagreement resolution. Missing, malformed, or stale locators block scoring.

## Scoring and severity

Retrieval reports Recall@k, MRR, nDCG, paper/page/object/region accuracy, locator replay, unresolved/stale counts, and abstention. Evidence reports accepted precision/recall, accepted-only violations, rejected/conflicted leakage, insufficiency and conflict recognition. Claims report supported rate, unsupported and critical unsupported claims, citation mismatch and critical mismatch, correct/incorrect abstain, false GO and false REVISE. Each of the eight Artifact types reports schema validity, required-field completeness, claim-to-evidence coverage, unsupported decisions, revision traceability, human approval, and final decision.

Severity is frozen as `critical`, `major`, `minor`, or `informational`. Critical includes unsupported verified claims, wrong paper/page/object/locator citations, rejected or conflicted evidence used for generation, fabricated results/citations, and unreplayable locators paired with definite conclusions. P0 GO requires critical unsupported claims = 0, critical citation mismatch = 0, and false GO = 0 with the exact frozen denominator; missing denominators are BLOCKED, never zero.

## Real environment and human gates

MiniLM evidence must record model/revision/source/hash, device/dtype/batch/dimension/normalization, index fingerprint, runtime, and environment. ColQwen2 must additionally record processor/model fingerprints, GPU/CUDA/dtype, rendering and resolution, batch, index/trace, OOM/retry, and degradation. The academic LLM trace must be redacted and retain provider/model/request/response hashes, usage, latency, retries, structured-output parsing, planner, ledger, claim validation, Artifact, and decision events. Native Windows requires manual clicks and screenshots; Playwright is not a substitute. An independent reviewer must approve/reject/revise all eight Artifact types and the final GO/REVISE/NO-GO.

## Stop and conclusion rules

Missing legal corpus, human labels, human scientific decisions, GPU/model revision, real academic LLM configuration, Native Windows click-through, or independent reviewer stops only that Gate and leaves it BLOCKED. Generated PDF, Fake/Mock, auto-generated labels, and LLM self-review cannot satisfy a Gate. GO is allowed only when every required Gate passes and all critical-zero metrics pass. Current required conclusion is **REVISE / P0 NO-GO**.

## Submission and handoff

Protocol changes are versioned; a formal run cannot silently edit this file or its digests. Acceptance work uses a stacked branch from the frozen pair and small reversible commits. Original Draft PRs remain open, Draft, and unmerged; no force push, reset, amend, direct main push, or automatic merge is allowed. The final handoff must report both repositories, start/final Heads, branches, PR states, exact pair and digests, corpus/question/gold/human/model/Native Windows/reviewer states, hard metrics (or BLOCKED/unscored), commands, tests, commits, uncommitted files, final REVISE decision, and the single next human action.

