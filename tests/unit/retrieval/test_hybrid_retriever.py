from __future__ import annotations

from dataclasses import replace

import pytest

from paperclaw.retrieval import (
    ChunkLocator,
    HybridCorpusMismatchError,
    HybridRetriever,
    RankedResult,
    RetrievalCandidate,
    RetrievalRequest,
    sha256_text,
)


class _StaticRetriever:
    def __init__(self, result: RankedResult) -> None:
        self.result = result
        self.requests: list[RetrievalRequest] = []

    def query(self, request: RetrievalRequest) -> RankedResult:
        self.requests.append(request)
        return self.result


def _candidate(chunk_id: str, rank: int, *, text: str | None = None) -> RetrievalCandidate:
    value = text or f"evidence for {chunk_id}"
    return RetrievalCandidate(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        version_id=f"version-{chunk_id}",
        display_name=f"{chunk_id}.md",
        canonical_uri=f"file:///workspace/{chunk_id}.md",
        text=value,
        content_hash=sha256_text(value),
        source_hash=sha256_text(f"source-{chunk_id}"),
        chunk_config_hash=sha256_text("config"),
        locator=ChunkLocator(
            source_uri=f"file:///workspace/{chunk_id}.md",
            heading_path=("Evidence",),
            start_line=1,
            end_line=2,
            start_paragraph=0,
            end_paragraph=0,
        ),
        bm25_score=float(10 - rank),
        rank=rank,
    )


def _result(name: str, candidates: tuple[RetrievalCandidate, ...], corpus: str) -> RankedResult:
    return RankedResult(
        request_id=f"request-{name}",
        manifest_id=f"manifest-{name}",
        corpus_hash=corpus,
        candidates=candidates,
        total_matches=len(candidates),
        filtered_stale=0,
        filtered_duplicates=0,
    )


def test_hybrid_rrf_is_deterministic_and_preserves_chunk_identity() -> None:
    corpus = sha256_text("shared-corpus")
    lexical = _StaticRetriever(
        _result("lexical", (_candidate("a", 1), _candidate("b", 2)), corpus)
    )
    semantic = _StaticRetriever(
        _result("semantic", (_candidate("b", 1), _candidate("c", 2)), corpus)
    )
    hybrid = HybridRetriever(
        (("lexical", lexical, 1.0), ("semantic", semantic, 1.0)),
        rrf_constant=10,
    )
    request = RetrievalRequest(query="evidence", top_k=3, candidate_pool_size=10)

    first = hybrid.query(request)
    second = hybrid.query(request)

    assert [item.chunk_id for item in first.candidates] == ["b", "a", "c"]
    assert first.to_dict() == second.to_dict()
    assert first.candidates[0].locator.source_uri.endswith("b.md")
    assert first.candidates[0].content_hash == _candidate("b", 1).content_hash
    assert all(call.top_k == 10 for call in lexical.requests + semantic.requests)


def test_hybrid_weight_changes_rank_without_changing_candidates() -> None:
    corpus = sha256_text("shared-corpus")
    lexical = _StaticRetriever(
        _result("lexical", (_candidate("a", 1), _candidate("b", 2)), corpus)
    )
    semantic = _StaticRetriever(
        _result("semantic", (_candidate("b", 1), _candidate("a", 2)), corpus)
    )
    hybrid = HybridRetriever(
        (("lexical", lexical, 3.0), ("semantic", semantic, 1.0)),
        rrf_constant=10,
    )

    result = hybrid.query(
        RetrievalRequest(query="evidence", top_k=2, candidate_pool_size=4)
    )
    assert [item.chunk_id for item in result.candidates] == ["a", "b"]
    assert result.candidates[0].rank == 1


def test_hybrid_rejects_corpus_mismatch() -> None:
    first = _StaticRetriever(
        _result("first", (_candidate("a", 1),), sha256_text("corpus-a"))
    )
    second = _StaticRetriever(
        _result("second", (_candidate("a", 1),), sha256_text("corpus-b"))
    )
    hybrid = HybridRetriever((("first", first, 1.0), ("second", second, 1.0)))

    with pytest.raises(HybridCorpusMismatchError):
        hybrid.query(RetrievalRequest(query="evidence"))


def test_hybrid_deduplicates_same_chunk_from_multiple_backends() -> None:
    corpus = sha256_text("shared")
    candidate = _candidate("same", 1)
    first = _StaticRetriever(_result("first", (candidate,), corpus))
    second = _StaticRetriever(
        _result("second", (replace(candidate, rank=1, bm25_score=1.0),), corpus)
    )
    result = HybridRetriever(
        (("first", first, 1.0), ("second", second, 1.0))
    ).query(RetrievalRequest(query="same", top_k=5))

    assert len(result.candidates) == 1
    assert result.filtered_duplicates >= 1
