"""Deterministic metrics for evidence-backed repository research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .contracts import CaseResult, EvalCase


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    value: float | int | None
    details: Mapping[str, Any]


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    variant_id: str
    status: str
    metrics: Mapping[str, MetricResult]
    plugin_failures: tuple[Mapping[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "variant_id": self.variant_id,
            "status": self.status,
            "metrics": {
                metric_id: {
                    "value": metric.value,
                    "details": dict(metric.details),
                }
                for metric_id, metric in sorted(self.metrics.items())
            },
            "plugin_failures": [dict(item) for item in self.plugin_failures],
        }


class EvalMetric(Protocol):
    metric_id: str
    version: str

    def evaluate(self, case: EvalCase, result: CaseResult) -> MetricResult: ...


class MetricRegistry:
    def __init__(self, plugins: Sequence[EvalMetric] = ()) -> None:
        plugins_tuple = tuple(plugins)
        ids = [plugin.metric_id for plugin in plugins_tuple]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate metric_id")
        self._plugins = plugins_tuple

    def score(self, case: EvalCase, result: CaseResult) -> CaseScore:
        base = core_metrics(case, result)
        failures: list[Mapping[str, str]] = []
        for plugin in self._plugins:
            try:
                metric = plugin.evaluate(case, result)
                if metric.metric_id != plugin.metric_id:
                    raise ValueError("plugin returned a different metric_id")
                base[metric.metric_id] = metric
            except Exception as exc:
                failures.append(
                    {
                        "metric_id": plugin.metric_id,
                        "version": plugin.version,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:500],
                    }
                )
        return CaseScore(
            case_id=case.case_id,
            variant_id=result.variant_id,
            status=result.status,
            metrics=base,
            plugin_failures=tuple(failures),
        )


def core_metrics(case: EvalCase, result: CaseResult) -> dict[str, MetricResult]:
    expected = {item.source_id for item in case.expected_evidence}
    ranked = sorted(result.hits, key=lambda item: (item.rank, item.source_id))
    retrieved = [item.source_id for item in ranked]
    retrieved_set = set(retrieved)
    top_k = max(1, min(5, len(ranked) or 1))
    claims_text = [_normalize(claim.text) for claim in result.claims]

    recall = _ratio(len(expected & set(retrieved[:top_k])), len(expected))
    first_relevant = next(
        (index for index, source_id in enumerate(retrieved, start=1) if source_id in expected),
        None,
    )
    mrr = 0.0 if first_relevant is None else 1.0 / first_relevant

    required_hits = sum(
        any(_normalize(required) in claim for claim in claims_text)
        for required in case.required_claims
    )
    forbidden_hits = sum(
        any(_normalize(forbidden) in claim for claim in claims_text)
        for forbidden in case.forbidden_claims
    )

    cited = [
        source_id
        for claim in result.claims
        for source_id in claim.source_ids
    ]
    correct_citations = sum(source_id in expected for source_id in cited)
    supported_claims = sum(
        bool(claim.source_ids)
        and all(source_id in retrieved_set for source_id in claim.source_ids)
        for claim in result.claims
    )
    claims_with_citations = sum(bool(claim.source_ids) for claim in result.claims)

    return {
        "recall_at_k": MetricResult(
            "recall_at_k",
            recall,
            {"k": top_k, "expected": len(expected), "retrieved": retrieved[:top_k]},
        ),
        "mrr": MetricResult(
            "mrr", mrr, {"first_relevant_rank": first_relevant}
        ),
        "required_claim_coverage": MetricResult(
            "required_claim_coverage",
            _ratio(required_hits, len(case.required_claims)),
            {"matched": required_hits, "required": len(case.required_claims)},
        ),
        "forbidden_claim_rate": MetricResult(
            "forbidden_claim_rate",
            _ratio(forbidden_hits, len(case.forbidden_claims)),
            {"matched": forbidden_hits, "forbidden": len(case.forbidden_claims)},
        ),
        "citation_correctness": MetricResult(
            "citation_correctness",
            _ratio(correct_citations, len(cited)),
            {"correct": correct_citations, "cited": len(cited)},
        ),
        "citation_completeness": MetricResult(
            "citation_completeness",
            _ratio(claims_with_citations, len(result.claims)),
            {
                "claims_with_citations": claims_with_citations,
                "claims": len(result.claims),
            },
        ),
        "unsupported_claim_rate": MetricResult(
            "unsupported_claim_rate",
            1.0 - _ratio(supported_claims, len(result.claims))
            if result.claims
            else 0.0,
            {"supported": supported_claims, "claims": len(result.claims)},
        ),
        "model_calls": MetricResult("model_calls", result.model_calls, {}),
        "tool_calls": MetricResult("tool_calls", result.tool_calls, {}),
        "mcp_calls": MetricResult("mcp_calls", result.mcp_calls, {}),
        "latency_ms": MetricResult("latency_ms", result.latency_ms, {}),
        "selected_context_items": MetricResult(
            "selected_context_items", result.selected_context_items, {}
        ),
    }


def aggregate_scores(scores: Sequence[CaseScore]) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for score in scores:
        for metric_id, metric in score.metrics.items():
            if isinstance(metric.value, (int, float)) and not isinstance(
                metric.value, bool
            ):
                buckets.setdefault(metric_id, []).append(float(metric.value))
    return {
        metric_id: sum(values) / len(values)
        for metric_id, values in sorted(buckets.items())
        if values
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
