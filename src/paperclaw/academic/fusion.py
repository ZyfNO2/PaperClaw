"""Weighted Reciprocal Rank Fusion for multi-channel academic retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChannelWeight:
    exact: float = 10.0
    lexical: float = 1.0
    dense: float = 0.8
    visual: float = 0.6


DEFAULT_WEIGHTS = ChannelWeight()
RRF_CONSTANT = 60


@dataclass(frozen=True)
class FusedCandidate:
    object_id: str
    fused_score: float
    channel_scores: dict[str, float] = field(default_factory=dict)
    channel_ranks: dict[str, int] = field(default_factory=dict)


def weighted_rrf(
    channel_rankings: dict[str, list[tuple[str, float]]],
    weights: ChannelWeight = DEFAULT_WEIGHTS,
    rrf_constant: int = RRF_CONSTANT,
) -> list[FusedCandidate]:
    scores: dict[str, float] = {}
    raw_scores: dict[str, dict[str, float]] = {}
    ranks: dict[str, dict[str, int]] = {}

    for channel, ranked in channel_rankings.items():
        weight = getattr(weights, channel, 0.5)
        if weight <= 0:
            continue
        for rank, (object_id, score) in enumerate(ranked, start=1):
            scores[object_id] = scores.get(object_id, 0.0) + weight / (
                rrf_constant + rank
            )
            raw_scores.setdefault(object_id, {})[channel] = score
            ranks.setdefault(object_id, {})[channel] = rank

    fused = [
        FusedCandidate(
            object_id=oid,
            fused_score=sc,
            channel_scores=raw_scores.get(oid, {}),
            channel_ranks=ranks.get(oid, {}),
        )
        for oid, sc in scores.items()
    ]
    fused.sort(key=lambda c: (-c.fused_score, c.object_id))
    return fused
