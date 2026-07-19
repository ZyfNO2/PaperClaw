from __future__ import annotations

from paperclaw.eval.aggregate import (
    MeteredChatModel,
    ModelPrice,
    PricingTable,
    UsageCollector,
    aggregate_runs,
    summarize_observations,
)
from paperclaw.models.base import ModelTurn
from paperclaw.trace import TraceEvent


class StaticReader:
    def __init__(self, rows):
        self.rows = rows

    def get_run_trace(self, run_id, *, since_sequence=0, require_terminal=False):
        events = tuple(e for e in self.rows[run_id] if e.sequence > since_sequence)
        if require_terminal and not any(e.event_type.startswith("run.") for e in events):
            raise ValueError("terminal required")
        return events

    def iter_run_trace(self, run_id, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


def event(run_id, sequence, event_type, *, status=None, duration=None, provider=None, model=None, error=None, payload=None):
    return TraceEvent(
        event_id=f"{run_id}-{sequence}",
        sequence=sequence,
        occurred_at=f"2026-07-20T00:00:0{sequence}+00:00",
        conversation_id="c1",
        run_id=run_id,
        event_type=event_type,
        component="model" if event_type.startswith("model.") else "tool" if event_type.startswith("tool.") else "runtime",
        status=status,
        duration_ms=duration,
        provider=provider,
        model=model,
        error_code=error,
        payload=payload or {},
    )


def test_aggregate_runs_reports_latency_quality_tokens_and_cost():
    reader = StaticReader(
        {
            "r1": (
                event("r1", 1, "run.started"),
                event("r1", 2, "model.started", provider="mistral", model="small"),
                event(
                    "r1",
                    3,
                    "model.completed",
                    duration=120,
                    provider="mistral",
                    model="small",
                    payload={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                ),
                event("r1", 4, "tool.started"),
                event("r1", 5, "tool.completed", duration=20),
                event("r1", 6, "run.completed", status="completed"),
            ),
            "r2": (
                event("r2", 1, "run.started"),
                event("r2", 2, "model.started", provider="mistral", model="small"),
                event(
                    "r2",
                    3,
                    "model.completed",
                    duration=200,
                    provider="mistral",
                    model="small",
                    payload={"input_tokens": 200, "output_tokens": 100, "total_tokens": 300, "retry_count": 1},
                ),
                event("r2", 4, "tool.started"),
                event("r2", 5, "tool.failed", status="failed", error="tool_timeout", duration=30),
                event("r2", 6, "run.failed", status="failed", error="tool_timeout"),
            ),
        }
    )
    pricing = PricingTable([ModelPrice("mistral", "small", 1.0, 2.0)])
    report = aggregate_runs(reader, ["r1", "r2"], pricing=pricing)

    assert report.run_count == 2
    assert report.success_count == 1
    assert report.success_rate == 0.5
    assert report.total_tokens == 450
    assert report.total_retries == 1
    assert report.total_tool_failures == 1
    assert report.tool_failure_rate == 0.5
    assert report.total_estimated_cost_usd == 0.0006
    assert report.unpriced_model_calls == 0
    assert report.failure_categories["tool_timeout"] == 2
    assert report.p50_wall_duration_ms is not None
    assert report.p95_wall_duration_ms is not None
    assert report.p99_wall_duration_ms is not None


def test_missing_price_is_explicit_not_zero_cost():
    reader = StaticReader(
        {
            "r": (
                event("r", 1, "run.started"),
                event("r", 2, "model.started", provider="unknown", model="x"),
                event(
                    "r",
                    3,
                    "model.completed",
                    provider="unknown",
                    model="x",
                    payload={"input_tokens": 10, "output_tokens": 5},
                ),
                event("r", 4, "run.completed", status="completed"),
            )
        }
    )
    report = aggregate_runs(reader, ["r"])
    assert report.priced_run_count == 0
    assert report.total_estimated_cost_usd == 0
    assert report.unpriced_model_calls == 1
    assert report.runs[0].estimated_cost_usd is None


class FakeModel:
    def complete(self, prompt: str) -> ModelTurn:
        return ModelTurn(
            content="ok",
            metadata={
                "provider": "mistral",
                "model": "small",
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "retry_count": 2,
            },
        )


def test_metered_model_collects_provider_usage_and_cost():
    collector = UsageCollector(PricingTable([ModelPrice("mistral", "small", 1, 2)]))
    model = MeteredChatModel(FakeModel(), collector)
    assert model.complete("hello").content == "ok"
    summary = summarize_observations(collector.snapshot())
    assert summary["model_calls"] == 1
    assert summary["input_tokens"] == 12
    assert summary["output_tokens"] == 3
    assert summary["retry_count"] == 2
    assert summary["estimated_cost_usd"] == 0.000018
