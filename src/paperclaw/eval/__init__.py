"""Deterministic evaluation plugins for PaperClaw traces."""

from .trace_eval import (
    EvalMetric,
    EvalThresholds,
    TraceEvalReport,
    evaluate_trace,
    render_trace_eval_text,
)

__all__ = [
    "EvalMetric",
    "EvalThresholds",
    "TraceEvalReport",
    "evaluate_trace",
    "render_trace_eval_text",
]
