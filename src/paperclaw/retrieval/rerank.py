"""Deterministic evidence-aware reranking over citation-preserving candidates."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
from typing import Protocol, Sequence

from paperclaw.retrieval.hybrid import HybridRetrievalResult, HybridRetriever
from paperclaw.retrieval.query import RetrievalCandidate, RetrievalRequest

_TOKEN = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


class CandidateReranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalCandidate],
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]: ...


@dataclass(frozen=True)
class EvidenceRerankConfig:
    exact_phrase_weight: float = 1.4
    token_coverage_weight: float = 2.0
    heading_weight: float = 0.35
    original_rank_weight: float = 0.6
    length_penalty_weight: float = 0.15
    diversity_penalty: float = 0.12

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")


class EvidenceAwareReranker:
    """Rerank using observable lexical evidence and source diversity.

    The reranker never changes citation identity. It only changes rank and the
    score field used for diagnostics. This makes it safe to compose after RRF.
    """

    def __init__(self, config: EvidenceRerankConfig | None = None) -> None:
        self.config = config or EvidenceRerankConfig()

    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalCandidate],
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        if not 1 <= top_k <= 1_000:
            raise ValueError("top_k must be in [1, 1000]")
        query_normalized = " ".join(query.casefold().split())
        query_tokens = tuple(dict.fromkeys(_TOKEN.findall(query_normalized)))
        query_set = set(query_tokens)
        scored: list[tuple[float, RetrievalCandidate]] = []
        for candidate in candidates:
            text_normalized = " ".join(candidate.text.casefold().split())
            text_tokens = set(_TOKEN.findall(text_normalized))
            coverage = (
                len(query_set & text_tokens) / len(query_set)
                if query_set
                else 0.0
            )
            exact_phrase = 1.0 if query_normalized and query_normalized in text_normalized else 0.0
            locator_text = f"{candidate.display_name} {candidate.locator.value}".casefold()
            heading_overlap = (
                len(query_set & set(_TOKEN.findall(locator_text))) / len(query_set)
                if query_set
                else 0.0
            )
            original_rank = max(1, candidate.rank)
            rank_prior = 1.0 / math.log2(original_rank + 1.0)
            length = max(1, len(text_tokens))
            length_penalty = max(0.0, math.log2(length / 220.0)) if length > 220 else 0.0
            score = (
                self.config.exact_phrase_weight * exact_phrase
                + self.config.token_coverage_weight * coverage
                + self.config.heading_weight * heading_overlap
                + self.config.original_rank_weight * rank_prior
                - self.config.length_penalty_weight * length_penalty
            )
            scored.append((round(score, 12), candidate))

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].rank,
                item[1].document_id,
                item[1].chunk_id,
            )
        )
        selected: list[RetrievalCandidate] = []
        document_counts: dict[str, int] = {}
        remaining = list(scored)
        while remaining and len(selected) < top_k:
            adjusted = [
                (
                    score
                    - self.config.diversity_penalty
                    * document_counts.get(candidate.document_id, 0),
                    score,
                    candidate,
                )
                for score, candidate in remaining
            ]
            adjusted.sort(
                key=lambda item: (
                    -item[0],
                    -item[1],
                    item[2].rank,
                    item[2].chunk_id,
                )
            )
            _, raw_score, candidate = adjusted[0]
            remaining = [item for item in remaining if item[1].chunk_id != candidate.chunk_id]
            document_counts[candidate.document_id] = document_counts.get(candidate.document_id, 0) + 1
            selected.append(
                replace(
                    candidate,
                    rank=len(selected) + 1,
                    bm25_score=raw_score,
                )
            )
        return tuple(selected)


@dataclass(frozen=True)
class RerankedHybridResult:
    request_id: str
    candidates: tuple[RetrievalCandidate, ...]
    fused_result: HybridRetrievalResult


class RerankedHybridRetriever:
    """Existing weighted-RRF HybridRetriever followed by a bounded reranker."""

    def __init__(
        self,
        hybrid: HybridRetriever,
        reranker: CandidateReranker | None = None,
    ) -> None:
        self.hybrid = hybrid
        self.reranker = reranker or EvidenceAwareReranker()

    def query(self, request: RetrievalRequest) -> RerankedHybridResult:
        fused = self.hybrid.query(request)
        reranked = self.reranker.rerank(
            request.normalized_query,
            fused.candidates,
            top_k=request.top_k,
        )
        return RerankedHybridResult(
            request_id=request.request_id,
            candidates=reranked,
            fused_result=fused,
        )


__all__ = [
    "CandidateReranker",
    "EvidenceAwareReranker",
    "EvidenceRerankConfig",
    "RerankedHybridResult",
    "RerankedHybridRetriever",
]
