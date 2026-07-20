"""Research-quality evaluation for retrieval, citations, grounding and abstention.

The evaluator consumes explicit benchmark facts and observed predictions. It does
not ask the answer-generating model to grade itself. Retrieval relevance, citation
support, claim support, latency, tokens and cost remain separate measurable fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from paperclaw.retrieval.evaluation import RetrievalEvalCase, evaluate_ranked_ids
from paperclaw.retrieval.query import RetrievalCandidate


@dataclass(frozen=True)
class ResearchQualityCase:
    case_id: str
    query: str
    relevant_chunk_ids: tuple[str, ...]
    relevant_document_ids: tuple[str, ...] = ()
    required_claim_ids: tuple[str, ...] = ()
    should_abstain: bool = False
    required_answer_terms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.query.strip():
            raise ValueError("case_id and query must be non-empty")
        if len(set(self.relevant_chunk_ids)) != len(self.relevant_chunk_ids):
            raise ValueError("relevant_chunk_ids must be unique")
        if len(set(self.relevant_document_ids)) != len(self.relevant_document_ids):
            raise ValueError("relevant_document_ids must be unique")
        if len(set(self.required_claim_ids)) != len(self.required_claim_ids):
            raise ValueError("required_claim_ids must be unique")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchQualityCase":
        return cls(
            case_id=str(payload["case_id"]),
            query=str(payload["query"]),
            relevant_chunk_ids=_strings(payload.get("relevant_chunk_ids", ())),
            relevant_document_ids=_strings(payload.get("relevant_document_ids", ())),
            required_claim_ids=_strings(payload.get("required_claim_ids", ())),
            should_abstain=bool(payload.get("should_abstain", False)),
            required_answer_terms=_strings(payload.get("required_answer_terms", ())),
            tags=_strings(payload.get("tags", ())),
        )


@dataclass(frozen=True)
class ResearchAnswerObservation:
    case_id: str
    ranked_chunk_ids: tuple[str, ...]
    ranked_document_ids: tuple[str, ...]
    cited_chunk_ids: tuple[str, ...] = ()
    cited_document_ids: tuple[str, ...] = ()
    claim_support: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    answer_text: str = ""
    abstained: bool = False
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        for name, value in (
            ("latency_ms", self.latency_ms),
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.estimated_cost_usd is not None:
            if (
                isinstance(self.estimated_cost_usd, bool)
                or not isinstance(self.estimated_cost_usd, (int, float))
                or not math.isfinite(float(self.estimated_cost_usd))
                or self.estimated_cost_usd < 0
            ):
                raise ValueError("estimated_cost_usd must be finite and non-negative")

    @classmethod
    def from_candidates(
        cls,
        case_id: str,
        candidates: Sequence[RetrievalCandidate],
        **kwargs: Any,
    ) -> "ResearchAnswerObservation":
        return cls(
            case_id=case_id,
            ranked_chunk_ids=tuple(item.chunk_id for item in candidates),
            ranked_document_ids=tuple(item.document_id for item in candidates),
            **kwargs,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchAnswerObservation":
        raw_support = payload.get("claim_support", {})
        if not isinstance(raw_support, Mapping):
            raise ValueError("claim_support must be an object")
        return cls(
            case_id=str(payload["case_id"]),
            ranked_chunk_ids=_strings(payload.get("ranked_chunk_ids", ())),
            ranked_document_ids=_strings(payload.get("ranked_document_ids", ())),
            cited_chunk_ids=_strings(payload.get("cited_chunk_ids", ())),
            cited_document_ids=_strings(payload.get("cited_document_ids", ())),
            claim_support={
                str(claim_id): _strings(citations)
                for claim_id, citations in raw_support.items()
            },
            answer_text=str(payload.get("answer_text", "")),
            abstained=bool(payload.get("abstained", False)),
            latency_ms=int(payload.get("latency_ms", 0)),
            input_tokens=int(payload.get("input_tokens", 0)),
            output_tokens=int(payload.get("output_tokens", 0)),
            estimated_cost_usd=(
                float(payload["estimated_cost_usd"])
                if payload.get("estimated_cost_usd") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ResearchCaseMetrics:
    case_id: str
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    document_recall_at_10: float
    citation_precision: float
    citation_recall: float
    grounded_claim_rate: float
    claim_coverage: float
    answer_term_coverage: float
    abstention_correct: bool
    latency_ms: int
    total_tokens: int
    estimated_cost_usd: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchQualityReport:
    case_count: int
    mean_recall_at_5: float
    mean_recall_at_10: float
    mean_mrr: float
    mean_ndcg_at_10: float
    mean_document_recall_at_10: float
    citation_precision: float
    citation_recall: float
    grounded_claim_rate: float
    claim_coverage: float
    answer_term_coverage: float
    abstention_accuracy: float
    total_latency_ms: int
    mean_latency_ms: float
    total_tokens: int
    total_estimated_cost_usd: float
    unpriced_case_count: int
    cases: tuple[ResearchCaseMetrics, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cases"] = [item.to_dict() for item in self.cases]
        return payload


@dataclass(frozen=True)
class QualityComparison:
    baseline: ResearchQualityReport
    candidate: ResearchQualityReport
    deltas: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "deltas": dict(self.deltas),
        }


def evaluate_research_quality(
    cases: Sequence[ResearchQualityCase],
    observations: Sequence[ResearchAnswerObservation],
) -> ResearchQualityReport:
    if not cases:
        raise ValueError("cases must not be empty")
    case_map = {case.case_id: case for case in cases}
    if len(case_map) != len(cases):
        raise ValueError("duplicate case_id in benchmark")
    observation_map = {item.case_id: item for item in observations}
    if len(observation_map) != len(observations):
        raise ValueError("duplicate case_id in observations")
    missing = sorted(set(case_map) - set(observation_map))
    extra = sorted(set(observation_map) - set(case_map))
    if missing or extra:
        raise ValueError(f"case mismatch: missing={missing} extra={extra}")

    metrics = tuple(
        evaluate_research_case(case_map[case_id], observation_map[case_id])
        for case_id in sorted(case_map)
    )
    costs = [item.estimated_cost_usd for item in metrics if item.estimated_cost_usd is not None]
    return ResearchQualityReport(
        case_count=len(metrics),
        mean_recall_at_5=_avg(item.recall_at_5 for item in metrics),
        mean_recall_at_10=_avg(item.recall_at_10 for item in metrics),
        mean_mrr=_avg(item.mrr for item in metrics),
        mean_ndcg_at_10=_avg(item.ndcg_at_10 for item in metrics),
        mean_document_recall_at_10=_avg(item.document_recall_at_10 for item in metrics),
        citation_precision=_avg(item.citation_precision for item in metrics),
        citation_recall=_avg(item.citation_recall for item in metrics),
        grounded_claim_rate=_avg(item.grounded_claim_rate for item in metrics),
        claim_coverage=_avg(item.claim_coverage for item in metrics),
        answer_term_coverage=_avg(item.answer_term_coverage for item in metrics),
        abstention_accuracy=_avg(float(item.abstention_correct) for item in metrics),
        total_latency_ms=sum(item.latency_ms for item in metrics),
        mean_latency_ms=round(mean(item.latency_ms for item in metrics), 6),
        total_tokens=sum(item.total_tokens for item in metrics),
        total_estimated_cost_usd=round(sum(costs), 12),
        unpriced_case_count=sum(item.estimated_cost_usd is None for item in metrics),
        cases=metrics,
    )


def evaluate_research_case(
    case: ResearchQualityCase,
    observation: ResearchAnswerObservation,
) -> ResearchCaseMetrics:
    if case.case_id != observation.case_id:
        raise ValueError("case_id mismatch")
    chunk_eval = evaluate_ranked_ids(
        RetrievalEvalCase(case.case_id, case.relevant_chunk_ids),
        observation.ranked_chunk_ids,
    )
    document_recall = _recall_at_k(
        observation.ranked_document_ids,
        case.relevant_document_ids,
        10,
    )
    relevant_citations = set(case.relevant_chunk_ids) | set(case.relevant_document_ids)
    observed_citations = set(observation.cited_chunk_ids) | set(observation.cited_document_ids)
    citation_precision = _precision(observed_citations, relevant_citations)
    citation_recall = _recall(observed_citations, relevant_citations)

    required_claims = set(case.required_claim_ids)
    supported_required = 0
    grounded_observed = 0
    for claim_id, citations in observation.claim_support.items():
        support_set = set(citations)
        grounded = bool(support_set & relevant_citations)
        grounded_observed += int(grounded)
        if claim_id in required_claims and grounded:
            supported_required += 1
    claim_coverage = (
        supported_required / len(required_claims)
        if required_claims
        else 1.0
    )
    grounded_claim_rate = (
        grounded_observed / len(observation.claim_support)
        if observation.claim_support
        else (1.0 if not required_claims and observation.abstained else 0.0)
    )
    required_terms = {item.casefold() for item in case.required_answer_terms}
    answer = observation.answer_text.casefold()
    answer_term_coverage = (
        sum(term in answer for term in required_terms) / len(required_terms)
        if required_terms
        else 1.0
    )
    return ResearchCaseMetrics(
        case_id=case.case_id,
        recall_at_5=chunk_eval.recall_at_5,
        recall_at_10=chunk_eval.recall_at_10,
        mrr=chunk_eval.mrr,
        ndcg_at_10=chunk_eval.ndcg_at_10,
        document_recall_at_10=round(document_recall, 6),
        citation_precision=round(citation_precision, 6),
        citation_recall=round(citation_recall, 6),
        grounded_claim_rate=round(grounded_claim_rate, 6),
        claim_coverage=round(claim_coverage, 6),
        answer_term_coverage=round(answer_term_coverage, 6),
        abstention_correct=observation.abstained == case.should_abstain,
        latency_ms=observation.latency_ms,
        total_tokens=observation.input_tokens + observation.output_tokens,
        estimated_cost_usd=observation.estimated_cost_usd,
    )


def compare_quality_reports(
    baseline: ResearchQualityReport,
    candidate: ResearchQualityReport,
) -> QualityComparison:
    if baseline.case_count != candidate.case_count:
        raise ValueError("reports must contain the same number of cases")
    fields = (
        "mean_recall_at_5",
        "mean_recall_at_10",
        "mean_mrr",
        "mean_ndcg_at_10",
        "mean_document_recall_at_10",
        "citation_precision",
        "citation_recall",
        "grounded_claim_rate",
        "claim_coverage",
        "answer_term_coverage",
        "abstention_accuracy",
    )
    deltas = {
        name: round(float(getattr(candidate, name)) - float(getattr(baseline, name)), 6)
        for name in fields
    }
    deltas.update(
        {
            "mean_latency_ms": round(candidate.mean_latency_ms - baseline.mean_latency_ms, 6),
            "total_tokens": float(candidate.total_tokens - baseline.total_tokens),
            "total_estimated_cost_usd": round(
                candidate.total_estimated_cost_usd - baseline.total_estimated_cost_usd,
                12,
            ),
        }
    )
    return QualityComparison(baseline, candidate, deltas)


def load_quality_cases(path: str | Path) -> tuple[ResearchQualityCase, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("cases", payload) if isinstance(payload, Mapping) else payload
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("benchmark must contain a list of cases")
    return tuple(ResearchQualityCase.from_mapping(item) for item in rows)


def load_quality_observations(path: str | Path) -> tuple[ResearchAnswerObservation, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("observations", payload) if isinstance(payload, Mapping) else payload
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("predictions must contain a list of observations")
    return tuple(ResearchAnswerObservation.from_mapping(item) for item in rows)


def _precision(observed: set[str], relevant: set[str]) -> float:
    if not observed:
        return 1.0 if not relevant else 0.0
    return len(observed & relevant) / len(observed)


def _recall(observed: set[str], relevant: set[str]) -> float:
    if not relevant:
        return 1.0
    return len(observed & relevant) / len(relevant)


def _recall_at_k(ranked: Sequence[str], relevant: Sequence[str], k: int) -> float:
    return _recall(set(ranked[:k]), set(relevant))


def _avg(values: Iterable[float]) -> float:
    rows = tuple(values)
    return round(mean(rows), 6) if rows else 0.0


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("expected a list of strings")
    rows = tuple(str(item) for item in value)
    if any(not item for item in rows):
        raise ValueError("list entries must be non-empty")
    return rows


__all__ = [
    "QualityComparison",
    "ResearchAnswerObservation",
    "ResearchCaseMetrics",
    "ResearchQualityCase",
    "ResearchQualityReport",
    "compare_quality_reports",
    "evaluate_research_case",
    "evaluate_research_quality",
    "load_quality_cases",
    "load_quality_observations",
]
