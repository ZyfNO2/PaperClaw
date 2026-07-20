"""Aggregate quality, latency, token, and cost evaluation for PaperClaw runs.

The module intentionally separates observed usage from pricing. Token counts and
latencies are durable facts from TraceEvent or a model wrapper; prices are an
operator-supplied policy that can change without rewriting historical traces.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import threading
import time
from typing import Any, Iterable, Mapping, Sequence

from paperclaw.models.base import ChatModel, ModelTurn
from paperclaw.trace import TraceEvent, TraceReader, inspect_run_trace


@dataclass(frozen=True)
class ModelPrice:
    """USD price per one million input/output tokens for one provider model."""

    provider: str
    model: str
    input_per_million_usd: float
    output_per_million_usd: float

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("provider and model must be non-empty")
        for name, value in (
            ("input_per_million_usd", self.input_per_million_usd),
            ("output_per_million_usd", self.output_per_million_usd),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


class PricingTable:
    """Immutable exact-match pricing policy.

    No network lookup or built-in current prices are used. Callers must provide
    the price facts they want applied to a report.
    """

    def __init__(self, prices: Iterable[ModelPrice] = ()) -> None:
        table: dict[tuple[str, str], ModelPrice] = {}
        for price in prices:
            key = (_norm(price.provider), _norm(price.model))
            if key in table:
                raise ValueError(f"duplicate price for {price.provider}/{price.model}")
            table[key] = price
        self._prices = table

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PricingTable":
        rows = payload.get("prices", payload)
        if isinstance(rows, Mapping):
            normalized: list[ModelPrice] = []
            for key, value in rows.items():
                if not isinstance(key, str) or "/" not in key or not isinstance(value, Mapping):
                    raise ValueError("pricing mapping keys must be 'provider/model'")
                provider, model = key.split("/", 1)
                normalized.append(
                    ModelPrice(
                        provider=provider,
                        model=model,
                        input_per_million_usd=float(value["input_per_million_usd"]),
                        output_per_million_usd=float(value["output_per_million_usd"]),
                    )
                )
            return cls(normalized)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise ValueError("prices must be a list or mapping")
        return cls(
            ModelPrice(
                provider=str(row["provider"]),
                model=str(row["model"]),
                input_per_million_usd=float(row["input_per_million_usd"]),
                output_per_million_usd=float(row["output_per_million_usd"]),
            )
            for row in rows
            if isinstance(row, Mapping)
        )

    def estimate(
        self,
        provider: str | None,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
    ) -> float | None:
        if not provider or not model:
            return None
        price = self._prices.get((_norm(provider), _norm(model)))
        if price is None:
            return None
        return round(
            (input_tokens * price.input_per_million_usd + output_tokens * price.output_per_million_usd)
            / 1_000_000,
            12,
        )


@dataclass(frozen=True)
class ModelCallObservation:
    provider: str | None
    model: str | None
    duration_ms: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    retry_count: int
    succeeded: bool
    estimated_cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UsageCollector:
    """Thread-safe collection of model-call observations for one team run."""

    def __init__(self, pricing: PricingTable | None = None) -> None:
        self._pricing = pricing or PricingTable()
        self._observations: list[ModelCallObservation] = []
        self._lock = threading.Lock()

    def record(
        self,
        *,
        provider: str | None,
        model: str | None,
        duration_ms: int,
        metadata: Mapping[str, Any] | None,
        succeeded: bool,
    ) -> ModelCallObservation:
        facts = metadata or {}
        input_tokens = _token(facts, "input_tokens", "prompt_tokens")
        output_tokens = _token(facts, "output_tokens", "completion_tokens")
        total_tokens = _token(facts, "total_tokens") or input_tokens + output_tokens
        retry_count = _token(facts, "retry_count", "retries")
        observed_provider = _text(facts.get("provider")) or provider
        observed_model = _text(facts.get("model")) or model
        observation = ModelCallObservation(
            provider=observed_provider,
            model=observed_model,
            duration_ms=max(0, int(duration_ms)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            retry_count=retry_count,
            succeeded=bool(succeeded),
            estimated_cost_usd=self._pricing.estimate(
                observed_provider,
                observed_model,
                input_tokens,
                output_tokens,
            ),
        )
        with self._lock:
            self._observations.append(observation)
        return observation

    def snapshot(self) -> tuple[ModelCallObservation, ...]:
        with self._lock:
            return tuple(self._observations)


class MeteredChatModel:
    """ChatModel decorator that records latency, token usage, retry count, and cost."""

    def __init__(
        self,
        delegate: ChatModel,
        collector: UsageCollector,
        *,
        provider: str | None = None,
        model: str | None = None,
        clock: Any = time.perf_counter,
    ) -> None:
        self._delegate = delegate
        self._collector = collector
        self._provider = provider
        self._model = model
        self._clock = clock

    def complete(self, prompt: str) -> ModelTurn:
        started = self._clock()
        try:
            turn = self._delegate.complete(prompt)
        except Exception:
            self._collector.record(
                provider=self._provider,
                model=self._model,
                duration_ms=round((self._clock() - started) * 1000),
                metadata=None,
                succeeded=False,
            )
            raise
        self._collector.record(
            provider=self._provider,
            model=self._model,
            duration_ms=round((self._clock() - started) * 1000),
            metadata=turn.metadata,
            succeeded=True,
        )
        return turn


@dataclass(frozen=True)
class RunAggregateMetrics:
    run_id: str
    terminal_event: str | None
    succeeded: bool
    wall_duration_ms: int | None
    model_duration_ms: int
    tool_duration_ms: int
    model_calls: int
    tool_calls: int
    tool_failures: int
    retries: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    unpriced_model_calls: int
    error_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateEvalReport:
    run_count: int
    success_count: int
    success_rate: float
    p50_wall_duration_ms: int | None
    p95_wall_duration_ms: int | None
    p99_wall_duration_ms: int | None
    total_model_calls: int
    total_tool_calls: int
    total_tool_failures: int
    tool_failure_rate: float
    total_retries: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_estimated_cost_usd: float
    priced_run_count: int
    unpriced_model_calls: int
    failure_categories: Mapping[str, int]
    runs: tuple[RunAggregateMetrics, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["failure_categories"] = dict(self.failure_categories)
        data["runs"] = [run.to_dict() for run in self.runs]
        return data


def evaluate_run_cost(
    reader: TraceReader,
    run_id: str,
    *,
    pricing: PricingTable | None = None,
    require_terminal: bool = True,
) -> RunAggregateMetrics:
    price_table = pricing or PricingTable()
    events = reader.get_run_trace(run_id, require_terminal=require_terminal)
    inspection = inspect_run_trace(reader, run_id, require_terminal=require_terminal)
    tool_failures = sum(event.event_type == "tool.failed" for event in events)
    costs: list[float] = []
    unpriced = 0
    for event in events:
        if event.event_type != "model.completed":
            continue
        input_tokens = _token(event.payload, "input_tokens", "prompt_tokens")
        output_tokens = _token(event.payload, "output_tokens", "completion_tokens")
        estimate = price_table.estimate(event.provider, event.model, input_tokens, output_tokens)
        if estimate is None:
            unpriced += 1
        else:
            costs.append(estimate)
    return RunAggregateMetrics(
        run_id=run_id,
        terminal_event=inspection.terminal_event,
        succeeded=inspection.terminal_event == "run.completed",
        wall_duration_ms=inspection.wall_duration_ms,
        model_duration_ms=inspection.model_duration_ms,
        tool_duration_ms=inspection.tool_duration_ms,
        model_calls=inspection.model_calls,
        tool_calls=inspection.tool_calls,
        tool_failures=tool_failures,
        retries=inspection.retry_count,
        input_tokens=inspection.input_tokens,
        output_tokens=inspection.output_tokens,
        total_tokens=inspection.total_tokens,
        estimated_cost_usd=round(sum(costs), 12) if costs else None,
        unpriced_model_calls=unpriced,
        error_count=inspection.error_count,
    )


def aggregate_runs(
    reader: TraceReader,
    run_ids: Sequence[str],
    *,
    pricing: PricingTable | None = None,
    require_terminal: bool = True,
) -> AggregateEvalReport:
    if not run_ids:
        raise ValueError("run_ids must not be empty")
    runs = tuple(
        evaluate_run_cost(
            reader,
            run_id,
            pricing=pricing,
            require_terminal=require_terminal,
        )
        for run_id in run_ids
    )
    durations = sorted(run.wall_duration_ms for run in runs if run.wall_duration_ms is not None)
    total_tool_calls = sum(run.tool_calls for run in runs)
    total_tool_failures = sum(run.tool_failures for run in runs)
    costs = [run.estimated_cost_usd for run in runs if run.estimated_cost_usd is not None]
    failures: dict[str, int] = {}
    for run_id in run_ids:
        for event in reader.get_run_trace(run_id, require_terminal=require_terminal):
            if not _is_failure_event(event):
                continue
            category = event.error_code or event.status or event.event_type
            failures[category] = failures.get(category, 0) + 1
    success_count = sum(run.succeeded for run in runs)
    return AggregateEvalReport(
        run_count=len(runs),
        success_count=success_count,
        success_rate=round(success_count / len(runs), 6),
        p50_wall_duration_ms=_percentile(durations, 0.50),
        p95_wall_duration_ms=_percentile(durations, 0.95),
        p99_wall_duration_ms=_percentile(durations, 0.99),
        total_model_calls=sum(run.model_calls for run in runs),
        total_tool_calls=total_tool_calls,
        total_tool_failures=total_tool_failures,
        tool_failure_rate=round(
            total_tool_failures / total_tool_calls if total_tool_calls else 0.0,
            6,
        ),
        total_retries=sum(run.retries for run in runs),
        total_input_tokens=sum(run.input_tokens for run in runs),
        total_output_tokens=sum(run.output_tokens for run in runs),
        total_tokens=sum(run.total_tokens for run in runs),
        total_estimated_cost_usd=round(sum(costs), 12),
        priced_run_count=len(costs),
        unpriced_model_calls=sum(run.unpriced_model_calls for run in runs),
        failure_categories=dict(sorted(failures.items())),
        runs=runs,
    )


def render_aggregate_eval_text(report: AggregateEvalReport) -> str:
    return "\n".join(
        [
            f"Runs: {report.run_count} | success: {report.success_count} ({report.success_rate:.2%})",
            (
                "Wall latency(ms): "
                f"p50={_display(report.p50_wall_duration_ms)} "
                f"p95={_display(report.p95_wall_duration_ms)} "
                f"p99={_display(report.p99_wall_duration_ms)}"
            ),
            (
                "Calls: "
                f"model={report.total_model_calls} tool={report.total_tool_calls} "
                f"tool_failures={report.total_tool_failures} "
                f"failure_rate={report.tool_failure_rate:.2%}"
            ),
            (
                "Tokens: "
                f"input={report.total_input_tokens} output={report.total_output_tokens} "
                f"total={report.total_tokens} retries={report.total_retries}"
            ),
            (
                "Cost(USD): "
                f"estimated={report.total_estimated_cost_usd:.12f} "
                f"priced_runs={report.priced_run_count} "
                f"unpriced_model_calls={report.unpriced_model_calls}"
            ),
            "Failures: " + (", ".join(f"{k}={v}" for k, v in report.failure_categories.items()) or "none"),
        ]
    )


def summarize_observations(
    observations: Sequence[ModelCallObservation],
) -> dict[str, int | float | None]:
    costs = [item.estimated_cost_usd for item in observations if item.estimated_cost_usd is not None]
    return {
        "model_calls": len(observations),
        "model_failures": sum(not item.succeeded for item in observations),
        "model_duration_ms": sum(item.duration_ms for item in observations),
        "input_tokens": sum(item.input_tokens for item in observations),
        "output_tokens": sum(item.output_tokens for item in observations),
        "total_tokens": sum(item.total_tokens for item in observations),
        "retry_count": sum(item.retry_count for item in observations),
        "estimated_cost_usd": round(sum(costs), 12) if costs else None,
        "unpriced_model_calls": sum(item.estimated_cost_usd is None for item in observations),
    }


def _percentile(values: Sequence[int], quantile: float) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return int(values[0])
    rank = (len(values) - 1) * quantile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return int(values[lower])
    interpolated = values[lower] + (values[upper] - values[lower]) * (rank - lower)
    return int(round(interpolated))


def _token(metadata: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return 0


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _norm(value: str) -> str:
    return value.strip().lower()


def _is_failure_event(event: TraceEvent) -> bool:
    return bool(
        event.error_code
        or event.status in {"failed", "blocked", "denied"}
        or event.event_type.endswith((".failed", ".blocked", ".denied"))
    )


def _display(value: int | None) -> str:
    return "-" if value is None else str(value)


__all__ = [
    "AggregateEvalReport",
    "MeteredChatModel",
    "ModelCallObservation",
    "ModelPrice",
    "PricingTable",
    "RunAggregateMetrics",
    "UsageCollector",
    "aggregate_runs",
    "evaluate_run_cost",
    "render_aggregate_eval_text",
    "summarize_observations",
]
