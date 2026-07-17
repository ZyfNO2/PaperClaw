from __future__ import annotations

from pathlib import Path

from paperclaw.retrieval import (
    ChunkConfig,
    IncrementalIndexer,
    RetrievalRequest,
    SQLiteBM25Retriever,
)


def test_document_scope_is_applied_before_candidate_pool_limit(tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    config = ChunkConfig(
        max_chars=500,
        min_chars=0,
        overlap_units=0,
        long_block_overlap_chars=20,
    )
    document_ids: dict[str, str] = {}
    with IncrementalIndexer(db, chunk_config=config) as indexer:
        for index in range(6):
            uri = f"file:///docs/{index}.md"
            result = indexer.index_bytes(
                canonical_uri=uri,
                display_name=f"{index}.md",
                media_type="text/markdown",
                content=f"# Shared\n\nscopepool common token document {index}".encode(),
            )
            document_ids[uri] = result.document_id

    target_uri = "file:///docs/5.md"
    with SQLiteBM25Retriever(db) as retriever:
        result = retriever.query(
            RetrievalRequest(
                query="scopepool",
                top_k=1,
                candidate_pool_size=1,
                document_ids=(document_ids[target_uri],),
            )
        )

    assert result.total_matches == 1
    assert [candidate.canonical_uri for candidate in result.candidates] == [target_uri]
