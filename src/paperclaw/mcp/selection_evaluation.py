"""Offline metrics for deterministic MCP capability selection fixtures."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class MCPToolSelectionJudgment:
    query_id: str
    selected_tools: tuple[str, ...]
    relevance: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not self.query_id.strip():
            raise ValueError("query_id must be non-empty")
        if len(set(self.selected_tools)) != len(self.selected_tools):
            raise ValueError("selected_tools must be unique")
        names = [name for name, _ in self.relevance]
        if len(set(names)) != len(names):
            raise ValueError("relevance tools must be unique")
        if any(grade < 0 for _, grade in self.relevance):
            raise ValueError("relevance grades must be non-negative")

    @classmethod
    def create(
        cls,
        *,
        query_id: str,
        selected_tools: Iterable[str],
        relevance: Mapping[str, int],
    ) -> "MCPToolSelectionJudgment":
        return cls(
            query_id=query_id,
            selected_tools=tuple(selected_tools),
            relevance=tuple(sorted((str(name), int(grade)) for name, grade in relevance.items())),
        )


@dataclass(frozen=True)
class MCPToolSelectionMetrics:
    recall_at_k: float
    mean_reciprocal_rank: float
    ndcg_at_k: float
    top1_accuracy: float
    k: int
    query_count: int

    def __post_init__(self) -> None:
        if self.k <= 0 or self.query_count <= 0:
            raise ValueError("k and query_count must be positive")
        for name in (
            "recall_at_k",
            "mean_reciprocal_rank",
            "ndcg_at_k",
            "top1_accuracy",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_tool_selection(
    judgments: Sequence[MCPToolSelectionJudgment],
    *,
    k: int,
) -> MCPToolSelectionMetrics:
    if not judgments:
        raise ValueError("judgments must be non-empty")
    if k <= 0:
        raise ValueError("k must be positive")
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    top1: list[float] = []
    for judgment in judgments:
        relevance = dict(judgment.relevance)
        relevant = {name for name, grade in relevance.items() if grade > 0}
        selected = judgment.selected_tools[:k]
        recalls.append(
            1.0 if not relevant else len(relevant.intersection(selected)) / len(relevant)
        )
        reciprocal_ranks.append(
            next(
                (
                    1.0 / rank
                    for rank, name in enumerate(judgment.selected_tools, start=1)
                    if relevance.get(name, 0) > 0
                ),
                0.0,
            )
        )
        actual = [relevance.get(name, 0) for name in selected]
        ideal = sorted((grade for grade in relevance.values() if grade > 0), reverse=True)[:k]
        ideal_dcg = _dcg(ideal)
        ndcgs.append(1.0 if ideal_dcg == 0.0 else _dcg(actual) / ideal_dcg)
        top1.append(
            1.0
            if judgment.selected_tools and relevance.get(judgment.selected_tools[0], 0) > 0
            else 0.0
        )
    return MCPToolSelectionMetrics(
        recall_at_k=fmean(recalls),
        mean_reciprocal_rank=fmean(reciprocal_ranks),
        ndcg_at_k=fmean(ndcgs),
        top1_accuracy=fmean(top1),
        k=k,
        query_count=len(judgments),
    )


def _dcg(grades: Sequence[int]) -> float:
    return sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(grades, start=1)
    )


__all__ = [
    "MCPToolSelectionJudgment",
    "MCPToolSelectionMetrics",
    "evaluate_tool_selection",
]
