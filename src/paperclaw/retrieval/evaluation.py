"""Offline retrieval metrics for deterministic retrieval fixtures."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class RetrievalJudgment:
    """One graded retrieval case keyed by stable candidate identifiers."""

    query_id: str
    retrieved_ids: tuple[str, ...]
    relevance: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not self.query_id.strip():
            raise ValueError("query_id must be non-empty")
        if len(set(self.retrieved_ids)) != len(self.retrieved_ids):
            raise ValueError("retrieved_ids must not contain duplicates")
        relevance_ids = [item_id for item_id, _ in self.relevance]
        if len(set(relevance_ids)) != len(relevance_ids):
            raise ValueError("relevance identifiers must be unique")
        if any(grade < 0 for _, grade in self.relevance):
            raise ValueError("relevance grades must be non-negative")

    @classmethod
    def create(
        cls,
        *,
        query_id: str,
        retrieved_ids: Iterable[str],
        relevance: Mapping[str, int],
    ) -> "RetrievalJudgment":
        return cls(
            query_id=query_id,
            retrieved_ids=tuple(retrieved_ids),
            relevance=tuple(
                sorted((str(key), int(value)) for key, value in relevance.items())
            ),
        )

    @property
    def relevance_map(self) -> dict[str, int]:
        return dict(self.relevance)


@dataclass(frozen=True)
class RetrievalMetrics:
    """Per-query or macro-averaged retrieval quality metrics."""

    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float
    k: int
    query_count: int = 1

    def __post_init__(self) -> None:
        if self.k <= 0:
            raise ValueError("k must be positive")
        if self.query_count <= 0:
            raise ValueError("query_count must be positive")
        for name in ("recall_at_k", "reciprocal_rank", "ndcg_at_k"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalEvalCase:
    """Binary relevance contract used by the v0.35 quality evaluator."""

    case_id: str
    relevant_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        if len(set(self.relevant_ids)) != len(self.relevant_ids):
            raise ValueError("relevant_ids must be unique")


@dataclass(frozen=True)
class RankedIdMetrics:
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_10: float


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int,
) -> float:
    """Binary Recall@K over all identifiers with a positive relevance grade."""

    _validate_k(k)
    relevant = {item_id for item_id, grade in relevance.items() if grade > 0}
    if not relevant:
        return 1.0
    hits = relevant.intersection(retrieved_ids[:k])
    return len(hits) / len(relevant)


def reciprocal_rank(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
) -> float:
    """Reciprocal rank of the first positively relevant result."""

    for rank, item_id in enumerate(retrieved_ids, start=1):
        if relevance.get(item_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int,
) -> float:
    """Graded nDCG@K using exponential gain and log2 discount."""

    _validate_k(k)
    actual = [relevance.get(item_id, 0) for item_id in retrieved_ids[:k]]
    ideal = sorted(
        (grade for grade in relevance.values() if grade > 0), reverse=True
    )[:k]
    ideal_score = _dcg(ideal)
    if ideal_score == 0.0:
        return 1.0
    return _dcg(actual) / ideal_score


def evaluate_judgment(judgment: RetrievalJudgment, *, k: int) -> RetrievalMetrics:
    """Evaluate one deterministic retrieval judgment."""

    relevance = judgment.relevance_map
    return RetrievalMetrics(
        recall_at_k=recall_at_k(judgment.retrieved_ids, relevance, k=k),
        reciprocal_rank=reciprocal_rank(judgment.retrieved_ids, relevance),
        ndcg_at_k=ndcg_at_k(judgment.retrieved_ids, relevance, k=k),
        k=k,
    )


def evaluate_suite(
    judgments: Sequence[RetrievalJudgment],
    *,
    k: int,
) -> RetrievalMetrics:
    """Return macro Recall@K, MRR and nDCG@K for an offline fixture suite."""

    _validate_k(k)
    if not judgments:
        raise ValueError("judgments must be non-empty")
    results = [evaluate_judgment(judgment, k=k) for judgment in judgments]
    return RetrievalMetrics(
        recall_at_k=fmean(result.recall_at_k for result in results),
        reciprocal_rank=fmean(result.reciprocal_rank for result in results),
        ndcg_at_k=fmean(result.ndcg_at_k for result in results),
        k=k,
        query_count=len(results),
    )


def evaluate_ranked_ids(
    case: RetrievalEvalCase,
    ranked_ids: Sequence[str],
) -> RankedIdMetrics:
    """Evaluate the fixed cutoffs used by research-quality reports.

    Cases with no relevant identifiers are retrieval-neutral. Abstention correctness
    is evaluated separately, so these cases receive perfect neutral retrieval scores
    instead of lowering the aggregate because no relevant item can exist.
    """

    if len(set(ranked_ids)) != len(ranked_ids):
        raise ValueError("ranked_ids must not contain duplicates")
    if not case.relevant_ids:
        return RankedIdMetrics(1.0, 1.0, 1.0, 1.0)
    relevance = {item_id: 1 for item_id in case.relevant_ids}
    return RankedIdMetrics(
        recall_at_5=round(recall_at_k(ranked_ids, relevance, k=5), 6),
        recall_at_10=round(recall_at_k(ranked_ids, relevance, k=10), 6),
        mrr=round(reciprocal_rank(ranked_ids, relevance), 6),
        ndcg_at_10=round(ndcg_at_k(ranked_ids, relevance, k=10), 6),
    )


def _dcg(grades: Sequence[int]) -> float:
    return sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(grades, start=1)
    )


def _validate_k(k: int) -> None:
    if k <= 0:
        raise ValueError("k must be positive")


__all__ = [
    "RankedIdMetrics",
    "RetrievalEvalCase",
    "RetrievalJudgment",
    "RetrievalMetrics",
    "evaluate_judgment",
    "evaluate_ranked_ids",
    "evaluate_suite",
    "ndcg_at_k",
    "recall_at_k",
    "reciprocal_rank",
]
