"""Label-based Citation Correctness and Unsupported Claim evaluation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any, Iterable, Sequence

from paperclaw.retrieval.context_source import CitationAnchor

_CITATION_LABEL = re.compile(r"\[C-[0-9a-f]{10}\]")


@dataclass(frozen=True)
class GroundingClaimJudgment:
    """One evaluated answer claim or abstention decision."""

    claim_id: str
    cited_anchor_ids: tuple[str, ...]
    supporting_anchor_ids: tuple[str, ...]
    answerable: bool = True
    abstained: bool = False

    def __post_init__(self) -> None:
        if not self.claim_id.strip():
            raise ValueError("claim_id must be non-empty")
        if len(set(self.cited_anchor_ids)) != len(self.cited_anchor_ids):
            raise ValueError("cited_anchor_ids must be unique")
        if len(set(self.supporting_anchor_ids)) != len(self.supporting_anchor_ids):
            raise ValueError("supporting_anchor_ids must be unique")
        if self.abstained and self.cited_anchor_ids:
            raise ValueError("an abstained claim must not contain citations")


@dataclass(frozen=True)
class GroundingMetrics:
    citation_correctness: float
    unsupported_claim_rate: float
    abstention_accuracy: float
    claim_count: int
    citation_count: int

    def __post_init__(self) -> None:
        if self.claim_count <= 0 or self.citation_count < 0:
            raise ValueError("claim_count must be positive and citation_count non-negative")
        for name in (
            "citation_correctness",
            "unsupported_claim_rate",
            "abstention_accuracy",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_grounding(
    judgments: Sequence[GroundingClaimJudgment],
    *,
    known_anchor_ids: Iterable[str],
) -> GroundingMetrics:
    """Evaluate citations against explicit offline support labels."""

    if not judgments:
        raise ValueError("judgments must be non-empty")
    known = set(known_anchor_ids)
    cited_total = 0
    cited_correct = 0
    made_claims = 0
    unsupported = 0
    abstention_outcomes: list[float] = []
    for judgment in judgments:
        supporting = set(judgment.supporting_anchor_ids)
        cited = set(judgment.cited_anchor_ids)
        cited_total += len(cited)
        cited_correct += len(cited.intersection(known).intersection(supporting))
        abstention_outcomes.append(
            1.0
            if (judgment.answerable and not judgment.abstained)
            or (not judgment.answerable and judgment.abstained)
            else 0.0
        )
        if judgment.abstained:
            continue
        made_claims += 1
        if not cited.intersection(known).intersection(supporting):
            unsupported += 1

    if cited_total:
        citation_correctness = cited_correct / cited_total
    else:
        citation_correctness = 1.0 if made_claims == 0 else 0.0
    unsupported_rate = unsupported / made_claims if made_claims else 0.0
    return GroundingMetrics(
        citation_correctness=citation_correctness,
        unsupported_claim_rate=unsupported_rate,
        abstention_accuracy=fmean(abstention_outcomes),
        claim_count=len(judgments),
        citation_count=cited_total,
    )


def cited_anchor_ids(
    answer: str,
    anchors: Iterable[CitationAnchor],
) -> tuple[str, ...]:
    """Resolve stable citation labels found in answer text to anchor IDs."""

    by_label = {anchor.label: anchor.anchor_id for anchor in anchors}
    resolved: list[str] = []
    for label in _CITATION_LABEL.findall(answer):
        anchor_id = by_label.get(label)
        if anchor_id is not None and anchor_id not in resolved:
            resolved.append(anchor_id)
    return tuple(resolved)


__all__ = [
    "GroundingClaimJudgment",
    "GroundingMetrics",
    "cited_anchor_ids",
    "evaluate_grounding",
]
