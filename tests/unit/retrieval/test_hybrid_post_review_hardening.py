from __future__ import annotations

from dataclasses import replace
import math

import pytest

from paperclaw.retrieval import (
    ChunkLocator,
    HybridCandidateMismatchError,
    HybridRetriever,
    RankedResult,
    RetrievalCandidate,
    RetrievalRequest,
    hybrid_configuration_fingerprint,
    sha256_text,
)


class _StaticRetriever:
    def __init__(self, result: RankedResult) -> None:
        self.result = result

    def query(self, _request: RetrievalRequest) -> RankedResult:
        return self.result


def _candidate(chunk_id: str, rank: int, *, text: str = "evidence") -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        document_id="doc",
        version_id="version",
        display_name="facts.md",
        canonical_uri="file:///workspace/facts.md",
        text=text,
        content_hash=sha256_text(text),
        source_hash=sha256_text("source"),
        chunk_config_hash=sha256_text("config"),
        locator=ChunkLocator(
            source_uri="file:///workspace/facts.md",
            heading_path=("Facts",),
            start_line=1,
            end_line=2,
            start_paragraph=0,
            end_paragraph=0,
        ),
        bm25_score=1.0,
        rank=rank,
    )


def _result(candidates: tuple[RetrievalCandidate, ...]) -> RankedResult:
    return RankedResult(
        request_id="request",
        manifest_id="manifest",
        corpus_hash=sha256_text("corpus"),
        candidates=candidates,
        total_matches=len(candidates),
        filtered_stale=0,
        filtered_duplicates=0,
    )


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), -1.0, 0.0, True])
def test_hybrid_rejects_non_finite_or_non_numeric_positive_weights(weight) -> None:
    retriever = _StaticRetriever(_result((_candidate("a", 1),)))
    with pytest.raises(ValueError, match="finite and positive"):
        HybridRetriever((("backend", retriever, weight),))
    with pytest.raises(ValueError, match="finite and positive"):
        hybrid_configuration_fingerprint((("backend", weight),))


def test_hybrid_rejects_conflicting_citation_identity_for_same_chunk() -> None:
    first = _StaticRetriever(_result((_candidate("same", 1, text="first"),)))
    second = _StaticRetriever(_result((_candidate("same", 1, text="second"),)))
    hybrid = HybridRetriever((('first', first, 1.0), ('second', second, 1.0)))

    with pytest.raises(HybridCandidateMismatchError, match="citation identity"):
        hybrid.query(RetrievalRequest(query="evidence"))


def test_hybrid_rejects_duplicate_chunk_within_one_backend() -> None:
    first = _candidate("same", 1)
    duplicate = replace(first, rank=2, bm25_score=0.5)
    backend = _StaticRetriever(_result((first, duplicate)))
    hybrid = HybridRetriever((("duplicate", backend, 1.0),))

    with pytest.raises(HybridCandidateMismatchError, match="duplicate chunk_id"):
        hybrid.query(RetrievalRequest(query="evidence"))


def test_hybrid_allows_same_identity_with_different_backend_scores() -> None:
    candidate = _candidate("same", 1)
    first = _StaticRetriever(_result((candidate,)))
    second = _StaticRetriever(
        _result((replace(candidate, rank=1, bm25_score=999.0),))
    )

    result = HybridRetriever(
        (("first", first, 1), ("second", second, 2.0)),
        rrf_constant=10,
    ).query(RetrievalRequest(query="evidence"))

    assert len(result.candidates) == 1
    assert result.candidates[0].chunk_id == "same"
    assert math.isfinite(result.candidates[0].bm25_score)
