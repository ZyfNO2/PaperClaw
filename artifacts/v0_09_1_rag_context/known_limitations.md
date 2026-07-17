# v0.09.1 RAG ContextSource / Citation — Known Limitations

- lexical BM25 evidence only; no embeddings, semantic entailment, RRF or reranker;
- no-answer policy is based on retrieval availability/count, not calibrated answer confidence;
- English fixed stopword list only; no language-specific analyzer selection;
- Citation Correctness and Unsupported Claim Rate require explicit offline support labels;
- no automatic claim segmentation or semantic support inference;
- citation labels are generated for current anchors and are not a long-term public document permalink;
- all indexed document content is treated as `external_untrusted`, including local files;
- Context budget may exclude lower-ranked evidence; excluded anchors must not be cited;
- exact duplicate filtering only; near-duplicate passages are not collapsed;
- no Provider answer-generation E2E; offline demo uses a deterministic label-bound answer;
- no online retrieval, PDF/OCR, HTML sanitizer or binary attachment handling;
- no automatic citation repair for arbitrary model output;
- stacked dependencies PR #24 and PR #25 must merge and be rebased before Ready for Review.
