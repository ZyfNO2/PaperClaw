# v0.09.1 BM25 / Incremental Retrieval — Known Limitations

- lexical FTS5 retrieval only; no embeddings, semantic expansion, stemming profile, RRF, or reranker;
- BM25 score is meaningful only inside one query/corpus snapshot and is not calibrated across corpora;
- exact duplicate filtering uses Chunk `content_hash`; near-duplicate detection is not included;
- a bounded candidate pool can return fewer than `top_k` after stale/duplicate filtering;
- index repair is explicit through `SQLiteIndexMaintainer`; user queries do not auto-rebuild corrupted storage;
- one `IncrementalIndexer` lock coordinates one process instance only; concurrent external mutators rely on the Registry transaction/Manifest Gate to fail closed;
- historical immutable versions are retained; reactivating an identical historical version is not supported by the Phase A unique-version contract;
- parsers remain Markdown/plain-text only; no PDF, OCR, HTML, notebook, or binary ingestion;
- the fixed four-query fixture is a deterministic regression Gate, not a representative retrieval benchmark;
- no ContextSource, CitationAnchor, answer grounding, no-answer policy, or Prompt integration;
- no online source refresh, filesystem watcher, scheduled compaction, or automatic garbage collection of inactive versions;
- rebuild trusts active Chunk rows as authoritative; corruption of those immutable rows requires external restore rather than FTS rebuild.
