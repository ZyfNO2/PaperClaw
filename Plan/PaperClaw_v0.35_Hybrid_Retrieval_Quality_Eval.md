# PaperClaw v0.35 — Hybrid Retrieval and Research-Quality Evaluation

## Goal

Move the existing retrieval foundation from lexical-only production use and
interface-only semantic seams to a reproducible hybrid research pipeline.

```text
Project chunks
  -> SQLite BM25 backend
  -> SQLite hashing-vector semantic backend
  -> weighted RRF
  -> evidence-aware reranker
  -> citation-preserving candidates
  -> research-quality evaluation
```

## Semantic/vector backend

- persistent SQLite corpus and manifest;
- deterministic signed feature hashing over normalized words, word bigrams and
  character n-grams;
- L2-normalized sparse vectors and cosine ranking;
- encoder fingerprint and corpus fingerprint;
- atomic corpus replace and bounded upsert;
- version, content hash, source hash, chunk configuration hash and locator remain
  attached to each candidate;
- backend implements the same `RetrievalRequest -> RankedResult` contract used by
  `HybridRetriever`.

This is a real local vector index, but it is not represented as a transformer or
hosted embedding model. Optional hosted/vector-store adapters remain possible
through the existing backend protocol.

## Hybrid fusion and reranking

- existing weighted reciprocal-rank fusion remains authoritative for backend fusion;
- semantic and lexical backend weights remain explicit;
- the evidence-aware reranker uses observable query coverage, exact phrase,
  heading/locator overlap, original rank and source diversity;
- reranking never changes citation identity, content hashes or locators;
- no hidden LLM judge is used for deterministic retrieval ordering.

## Research-quality evaluation

Benchmark cases contain explicit facts:

- relevant chunk ids;
- relevant document ids;
- required claim ids;
- expected abstention;
- required answer terms;
- optional tags.

Predictions contain observed outputs:

- ranked chunks and documents;
- cited chunks and documents;
- claim-to-citation support mapping;
- answer text and abstention decision;
- latency, tokens and estimated cost.

Metrics:

- Recall@5 / Recall@10;
- MRR;
- nDCG@10;
- document Recall@10;
- citation precision and recall;
- grounded claim rate;
- required-claim coverage;
- required-answer-term coverage;
- abstention accuracy;
- latency, token and cost totals;
- baseline-to-candidate deltas.

## CLI

```bash
paperclaw-retrieval-quality \
  --benchmark benchmark.json \
  --predictions hybrid.json \
  --baseline lexical.json \
  --format json
```

## Acceptance

1. semantic index persists and reopens with the same corpus fingerprint;
2. semantic ranking returns the relevant vector passage;
3. weighted RRF includes lexical and semantic evidence;
4. reranker improves evidence ordering without changing citation identity;
5. hybrid quality beats the lexical baseline on a deterministic benchmark;
6. citation, grounding and abstention metrics are independently inspectable;
7. cost and latency deltas remain visible instead of being hidden behind one score;
8. existing retrieval, v0.34 distributed and full repository tests remain green;
9. package `0.35.0` exposes the quality CLI.

## Explicit limits

- hashing embeddings capture lexical/subword semantics, not transformer-level meaning;
- full transformer, hosted embedding and external vector DB adapters are not bundled;
- deterministic groundedness uses explicit claim-support observations, not natural-language
  entailment inference;
- benchmark quality depends on curated relevance and claim labels;
- scientific answer generation remains outside the evaluator and is never self-graded;
- Project-scoped Skills and Connectors are v0.36 scope.
