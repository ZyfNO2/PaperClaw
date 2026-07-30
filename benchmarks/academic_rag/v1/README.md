# Academic RAG H0 Corpus Benchmark (v1)

Frozen corpus manifest for the Academic RAG P0 acceptance pipeline.

## Files

| File | Description |
|------|-------------|
| `corpus_manifest.jsonl` | 107 entries; per-paper metadata, SHA-256, parser status |
| `frozen_12.json` | 12-paper frozen validation set (blind IDs P01–P12) |
| `invalid_input_decisions.jsonl` | Triage decisions for 10 failed inputs |

## Manifest digest

```text
manifest_sha256: 389be651cc8ca001f0d8cf2a5be3343ba7764407bc0f4669d620b37c5135ea20
```

## Frozen 12 category distribution

| Category | Count | Blind IDs |
|----------|------:|-----------|
| crack_detection | 3 | P01, P02, P03 |
| reconstruction_3d_stereo | 3 | P04, P05, P06 |
| segmentation | 3 | P07, P08, P09 |
| concrete_material | 3 | P10, P11, P12 |

## Invalid input summary

| Decision | Count |
|----------|------:|
| reacquire | 7 |
| exclude | 2 |
| quarantine | 1 |

## Reproducibility

```powershell
python scripts/generate_corpus_manifest.py
python scripts/verify_corpus_manifest.py
```

Requires `data/paper_corpus/` (untracked, local only) and `pypdf`.

## Real-paper locator inventory

Generate a local-only label inventory from the frozen 12 papers:

```powershell
python scripts/academic_frozen_inventory.py `
  --corpus data/paper_corpus `
  --manifest benchmarks/academic_rag/v1/corpus_manifest.jsonl `
  --frozen-set benchmarks/academic_rag/v1/frozen_12.json `
  --workspace build/frozen-12-inventory `
  --output output/frozen-12-locator-inventory.json
```

The command resolves every PDF by SHA-256, imports and parses all 12 papers,
incrementally synchronizes each version into the canonical object index, and
emits bounded Table/Cell/Equation/Algorithm/Caption/Section candidates for
human labelling. The output contains short text previews and must remain local;
it is bound to the reported `index_generation_id` and is not a gold dataset.

## Constraints

- Original PDFs are NOT committed; only metadata and hashes.
- No local absolute paths, usernames, or private directory structure in committed files.
- UTF-8, no BOM, LF line endings, fixed JSON key order, sorted by entry_id.
- This manifest is a corpus integrity record, not a scientific validation result.
- The 32 blinded questions and gold labels belong to H5 and are NOT included here.
## 32-question human-label template

`eval/questions.template.jsonl` contains exactly 32 blinded authoring slots: eight
each for text, Figure, Table, and Equation retrieval. Every row is deliberately
`pending_human_labeling`; `gold_locator`, bbox/table-cell targets, abstention target,
paper identity, and fingerprint must be filled from human review of the frozen
corpus. `validate_blinded_question_file` returns `blocked_by_human_labeling` until
all rows are marked `human_verified` with a gold locator. Automated generation must
not convert this template into purported human gold.
