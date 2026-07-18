"""Reproducible repository-research dataset, metrics and plugin APIs."""

from .contracts import (
    CaseResult,
    EvalCase,
    EvaluatedClaim,
    EvidenceExpectation,
    EvidenceHit,
    load_dataset,
    load_recorded_results,
)
from .metrics import EvalMetric, MetricRegistry, MetricResult
from .runner import (
    CapabilityProvider,
    EvaluationRunner,
    JsonReportRenderer,
    MarkdownReportRenderer,
    RecordedVariant,
    RetrievalVariant,
    StaticRegistry,
    compare_reports,
    write_report,
)

__all__ = [
    "CapabilityProvider",
    "CaseResult",
    "EvalCase",
    "EvalMetric",
    "EvaluatedClaim",
    "EvaluationRunner",
    "EvidenceExpectation",
    "EvidenceHit",
    "JsonReportRenderer",
    "MarkdownReportRenderer",
    "MetricRegistry",
    "MetricResult",
    "RecordedVariant",
    "RetrievalVariant",
    "StaticRegistry",
    "compare_reports",
    "load_dataset",
    "load_recorded_results",
    "write_report",
]
