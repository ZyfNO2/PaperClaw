from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from paperclaw.retrieval import (
    ChunkConfig,
    IncrementalIndexer,
    RetrievalJudgment,
    RetrievalRequest,
    SQLiteBM25Retriever,
    SQLiteIndexMaintainer,
    StaleIndexError,
    evaluate_suite,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    retrieved_ids,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "retrieval_bm25_fixture.json"
CONFIG = ChunkConfig(
    max_chars=800,
    min_chars=0,
    overlap_units=0,
    long_block_overlap_chars=40,
)


def _index(
    indexer: IncrementalIndexer,
    uri: str,
    text: str,
    *,
    name: str | None = None,
):
    return indexer.index_bytes(
        canonical_uri=uri,
        display_name=name or uri.rsplit("/", 1)[-1],
        media_type="text/markdown",
        content=text.encode("utf-8"),
    )


def test_retrieval_request_is_deterministic_and_bounded() -> None:
    first = RetrievalRequest(query="  WAL   timeout ", top_k=3, candidate_pool_size=10)
    second = RetrievalRequest(query="WAL timeout", top_k=3, candidate_pool_size=10)
    assert first.request_id == second.request_id
    assert first.normalized_query == "WAL timeout"
    with pytest.raises(ValueError, match="candidate_pool_size"):
        RetrievalRequest(query="x", top_k=5, candidate_pool_size=4)


def test_incremental_add_noop_update_delete_and_snapshot_invalidation(tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    uri = "file:///docs/runtime.md"
    old_text = "# Runtime\n\nalphaunique event loop cancellation semantics"
    new_text = "# Runtime\n\nnebulaunique replacement content and cleanup semantics"

    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        added = _index(indexer, uri, old_text)
        noop = _index(indexer, uri, old_text)
        assert added.operation == "add"
        assert noop.operation == "noop"
        assert noop.version_id == added.version_id
        old_manifest = indexer.registry.latest_manifest()
        assert old_manifest is not None

        with SQLiteBM25Retriever(db) as retriever:
            old_result = retriever.query(RetrievalRequest(query="alphaunique", top_k=3))
            assert [candidate.canonical_uri for candidate in old_result.candidates] == [uri]
            assert old_result.fingerprint == retriever.query(
                RetrievalRequest(query="alphaunique", top_k=3)
            ).fingerprint

        updated = _index(indexer, uri, new_text)
        assert updated.operation == "update"
        assert updated.version_id != added.version_id
        assert updated.deactivated_versions == 1
        assert updated.deactivated_chunks >= 1

        with SQLiteBM25Retriever(db) as retriever:
            assert not retriever.query(
                RetrievalRequest(query="alphaunique", top_k=3)
            ).candidates
            new_result = retriever.query(RetrievalRequest(query="nebulaunique", top_k=3))
            assert [candidate.canonical_uri for candidate in new_result.candidates] == [uri]
            with pytest.raises(StaleIndexError):
                retriever.query(
                    RetrievalRequest(
                        query="nebulaunique",
                        expected_manifest_id=old_manifest.manifest_id,
                    )
                )

        deleted = indexer.delete_document(updated.document_id)
        assert deleted.operation == "delete"

    with SQLiteBM25Retriever(db) as retriever:
        assert not retriever.query(
            RetrievalRequest(query="nebulaunique", top_k=3)
        ).candidates


def test_duplicate_content_is_filtered_after_bm25_ranking(tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    text = "# Shared\n\nquasarduplicate exact shared retrieval payload"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        _index(indexer, "file:///docs/a.md", text)
        _index(indexer, "file:///docs/b.md", text)

    with SQLiteBM25Retriever(db) as retriever:
        filtered = retriever.query(
            RetrievalRequest(query="quasarduplicate", top_k=5, deduplicate=True)
        )
        unfiltered = retriever.query(
            RetrievalRequest(query="quasarduplicate", top_k=5, deduplicate=False)
        )
    assert len(filtered.candidates) == 1
    assert filtered.filtered_duplicates == 1
    assert len(unfiltered.candidates) == 2


def test_stale_fts_rows_are_invalidated_at_read_time(tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        _index(indexer, "file:///docs/orion.md", "# Orion\n\noriontoken active evidence")

    connection = sqlite3.connect(db)
    connection.execute(
        "INSERT INTO chunk_fts(chunk_id, document_id, version_id, heading, text) "
        "VALUES (?, ?, ?, ?, ?)",
        ("stale_chunk", "stale_doc", "stale_version", "Stale", "oriontoken stale evidence"),
    )
    connection.commit()
    connection.close()

    with SQLiteBM25Retriever(db) as retriever:
        result = retriever.query(
            RetrievalRequest(query="oriontoken", top_k=3, candidate_pool_size=10)
        )
    assert len(result.candidates) == 1
    assert result.filtered_stale == 1
    assert result.candidates[0].canonical_uri == "file:///docs/orion.md"


def test_broken_index_is_detected_and_rebuilt_from_active_chunks(tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        _index(indexer, "file:///docs/rebuild.md", "# Rebuild\n\nphoenixrebuild active text")

    connection = sqlite3.connect(db)
    connection.execute("DELETE FROM chunk_fts")
    connection.execute(
        "INSERT INTO chunk_fts(chunk_id, document_id, version_id, heading, text) "
        "VALUES ('ghost', 'ghost-doc', 'ghost-version', 'Ghost', 'phoenixrebuild ghost')"
    )
    connection.commit()
    connection.close()

    with SQLiteIndexMaintainer(db, chunk_config=CONFIG) as maintainer:
        before = maintainer.inspect()
        assert before.is_broken
        assert before.missing_fts_rows == 1
        assert before.stale_fts_rows == 1
        rebuilt = maintainer.rebuild()
        assert rebuilt.rebuilt
        assert not rebuilt.after.is_broken
        assert rebuilt.written_fts_rows == 1
        assert maintainer.rebuild().rebuilt is False

    with SQLiteBM25Retriever(db) as retriever:
        result = retriever.query(RetrievalRequest(query="phoenixrebuild"))
    assert len(result.candidates) == 1


def test_metric_definitions_are_graded_and_deterministic() -> None:
    relevance = {"a": 3, "b": 1}
    assert recall_at_k(("a", "x"), relevance, k=1) == 0.5
    assert reciprocal_rank(("x", "b", "a"), relevance) == 0.5
    assert ndcg_at_k(("a", "b"), relevance, k=2) == 1.0


def test_fixed_retrieval_fixture_meets_offline_quality_gate(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    db = tmp_path / "fixture.db"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        for document in fixture["documents"]:
            indexer.index_bytes(
                canonical_uri=document["uri"],
                display_name=document["name"],
                media_type=document["media_type"],
                content=document["text"].encode("utf-8"),
            )

    judgments = []
    with SQLiteBM25Retriever(db) as retriever:
        for query in fixture["queries"]:
            result = retriever.query(
                RetrievalRequest(query=query["query"], top_k=3, candidate_pool_size=20)
            )
            judgments.append(
                RetrievalJudgment.create(
                    query_id=query["id"],
                    retrieved_ids=retrieved_ids(result, field="canonical_uri"),
                    relevance=query["relevance"],
                )
            )

    metrics = evaluate_suite(judgments, k=3)
    assert metrics.query_count == len(fixture["queries"])
    assert metrics.recall_at_k == 1.0
    assert metrics.reciprocal_rank == 1.0
    assert metrics.ndcg_at_k == 1.0
