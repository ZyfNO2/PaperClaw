"""Deterministic evaluation and aggregate observability for PaperClaw runs."""

from .aggregate import (
    AggregateEvalReport,
    MeteredChatModel,
    ModelCallObservation,
    ModelPrice,
    PricingTable,
    RunAggregateMetrics,
    UsageCollector,
    aggregate_runs,
    evaluate_run_cost,
    render_aggregate_eval_text,
    summarize_observations,
)
from .trace_eval import (
    EvalMetric,
    EvalThresholds,
    TraceEvalReport,
    evaluate_trace,
    render_trace_eval_text,
)

__all__ = [
    "AggregateEvalReport",
    "EvalMetric",
    "EvalThresholds",
    "MeteredChatModel",
    "ModelCallObservation",
    "ModelPrice",
    "PricingTable",
    "RunAggregateMetrics",
    "TraceEvalReport",
    "UsageCollector",
    "aggregate_runs",
    "evaluate_run_cost",
    "evaluate_trace",
    "render_aggregate_eval_text",
    "render_trace_eval_text",
    "summarize_observations",
]
from .case_loader import CaseValidationError, load_cases, parse_case
from .case_runner import run_case, run_cases
from .contracts import EvaluationCase, EvaluationFailure, EvaluationResult

__all__ += [
    "CaseValidationError", "EvaluationCase", "EvaluationFailure", "EvaluationResult",
    "load_cases", "parse_case", "run_case", "run_cases",
]
