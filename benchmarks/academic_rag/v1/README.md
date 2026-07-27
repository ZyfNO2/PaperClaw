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

## Constraints

- Original PDFs are NOT committed; only metadata and hashes.
- No local absolute paths, usernames, or private directory structure in committed files.
- UTF-8, no BOM, LF line endings, fixed JSON key order, sorted by entry_id.
- This manifest is a corpus integrity record, not a scientific validation result.
- The 32 blinded questions and gold labels belong to H5 and are NOT included here.
