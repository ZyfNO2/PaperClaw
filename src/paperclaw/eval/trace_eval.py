"""Deterministic, LLM-free evaluation over durable TraceEvent facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from paperclaw.replay import replay_recorded_trace
from paperclaw.trace import TraceEvent, TraceReader, inspect_run_trace


@dataclass(frozen=True)
class EvalThresholds:
    require_completed: bool = False
    require_replay_faithful: bool = True
    max_tool_failure_rate: float | None = None
    max_retries: int | None = None
    max_errors: int | None = None
    max_wall_duration_ms: int | None = None
    max_reflection_rounds: int | None = None

    def __post_init__(self) -> None:
        if self.max_tool_failure_rate is not None and not (
            0 <= self.max_tool_failure_rate <= 1
        ):
            raise ValueError("max_tool_failure_rate must be between 0 and 1")
        for name, value in (
            ("max_retries", self.max_retries),
            ("max_errors", self.max_errors),
            ("max_wall_duration_ms", self.max_wall_duration_ms),
            ("max_reflection_rounds", self.max_reflection_rounds),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class EvalMetric:
    name: str
    value: bool | int | float | str | None
    unit: str | None = None
    passed: bool | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceEvalReport:
    run_id: str
    conversation_id: str
    terminal_event: str | None
    overall_passed: bool
    failed_checks: tuple[str, ...]
    metrics: tuple[EvalMetric, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["failed_checks"] = list(self.failed_checks)
        data["metrics"] = [metric.to_dict() for metric in self.metrics]
        return data


def evaluate_trace(
    reader: TraceReader,
    run_id: str,
    *,
    thresholds: EvalThresholds | None = None,
    require_terminal: bool = True,
) -> TraceEvalReport:
    policy = thresholds or EvalThresholds()
    events = reader.get_run_trace(run_id, require_terminal=require_terminal)
    static_reader = _StaticTraceReader(events)
    inspection = inspect_run_trace(
        static_reader,
        run_id,
        require_terminal=require_terminal,
    )
    replay = replay_recorded_trace(
        static_reader,
        run_id,
        require_terminal=require_terminal,
    )

    terminal_completed = inspection.terminal_event == "run.completed"
    tool_failures = sum(event.event_type == "tool.failed" for event in events)
    tool_failure_rate = (
        tool_failures / inspection.tool_calls if inspection.tool_calls else 0.0
    )
    reflection_rounds = sum(
        event.event_type == "reflection.started" for event in events
    )
    verification = _verification_result(events)

    metrics = [
        EvalMetric(
            name="terminal_completed",
            value=terminal_completed,
            passed=terminal_completed if policy.require_completed else None,
            detail=inspection.terminal_event,
        ),
        EvalMetric(
            name="recorded_replay_faithful",
            value=replay.faithful,
            passed=(replay.faithful if policy.require_replay_faithful else None),
            detail=f"issues={replay.issue_count}",
        ),
        EvalMetric(
            name="verification",
            value=verification,
            detail="derived from verification.completed when recorded",
        ),
        EvalMetric(
            name="reflection_rounds",
            value=reflection_rounds,
            unit="rounds",
            passed=_max_check(reflection_rounds, policy.max_reflection_rounds),
        ),
        EvalMetric(
            name="tool_failure_rate",
            value=round(tool_failure_rate, 6),
            unit="ratio",
            passed=_max_check(tool_failure_rate, policy.max_tool_failure_rate),
            detail=f"failures={tool_failures}, calls={inspection.tool_calls}",
        ),
        EvalMetric(
            name="provider_retries",
            value=inspection.retry_count,
            unit="retries",
            passed=_max_check(inspection.retry_count, policy.max_retries),
        ),
        EvalMetric(
            name="error_count",
            value=inspection.error_count,
            unit="events",
            passed=_max_check(inspection.error_count, policy.max_errors),
        ),
        EvalMetric(
            name="wall_duration_ms",
            value=inspection.wall_duration_ms,
            unit="ms",
            passed=_max_check(
                inspection.wall_duration_ms,
                policy.max_wall_duration_ms,
            ),
        ),
        EvalMetric(
            name="model_duration_ms",
            value=inspection.model_duration_ms,
            unit="ms",
        ),
        EvalMetric(
            name="tool_duration_ms",
            value=inspection.tool_duration_ms,
            unit="ms",
        ),
        EvalMetric(
            name="input_tokens",
            value=inspection.input_tokens,
            unit="tokens",
        ),
        EvalMetric(
            name="output_tokens",
            value=inspection.output_tokens,
            unit="tokens",
        ),
        EvalMetric(
            name="total_tokens",
            value=inspection.total_tokens,
            unit="tokens",
        ),
    ]
    failed = tuple(metric.name for metric in metrics if metric.passed is False)
    return TraceEvalReport(
        run_id=inspection.run_id,
        conversation_id=inspection.conversation_id,
        terminal_event=inspection.terminal_event,
        overall_passed=not failed,
        failed_checks=failed,
        metrics=tuple(metrics),
    )


def render_trace_eval_text(report: TraceEvalReport) -> str:
    lines = [
        f"Trace eval: {report.run_id}",
        f"Terminal: {report.terminal_event or '-'}",
        f"Overall: {'PASS' if report.overall_passed else 'FAIL'}",
        "",
        "Metrics:",
    ]
    for metric in report.metrics:
        gate = (
            "PASS"
            if metric.passed is True
            else "FAIL"
            if metric.passed is False
            else "INFO"
        )
        unit = f" {metric.unit}" if metric.unit else ""
        detail = f" — {metric.detail}" if metric.detail else ""
        lines.append(f"{gate:>4} {metric.name}={metric.value}{unit}{detail}")
    if report.failed_checks:
        lines.extend(["", "Failed checks: " + ", ".join(report.failed_checks)])
    return "\n".join(lines)


class _StaticTraceReader:
    def __init__(self, events: tuple[TraceEvent, ...]) -> None:
        self._events = events

    def get_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> tuple[TraceEvent, ...]:
        events = tuple(
            event for event in self._events if event.sequence > since_sequence
        )
        if events and events[0].run_id != run_id:
            raise ValueError(f"trace run mismatch: expected {run_id}")
        if require_terminal and not any(
            event.event_type.startswith("run.")
            and event.event_type.rsplit(".", 1)[-1]
            in {"completed", "failed", "stopped", "cancelled"}
            for event in events
        ):
            raise ValueError("trace does not contain a terminal event")
        return events

    def iter_run_trace(self, run_id: str, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


def _verification_result(events: tuple[TraceEvent, ...]) -> bool | str:
    completed = [
        event for event in events if event.event_type == "verification.completed"
    ]
    if not completed:
        return "not_recorded"
    payload = completed[-1].payload
    candidates: list[Any] = [payload]
    result = payload.get("result")
    if isinstance(result, dict):
        candidates.append(result)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        passed = candidate.get("passed")
        if isinstance(passed, bool):
            return passed
        for key in ("status", "verdict"):
            value = candidate.get(key)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"pass", "passed", "verified", "success", "approved"}:
                    return True
                if normalized in {"fail", "failed", "rejected", "blocked"}:
                    return False
    return "unknown"


def _max_check(
    value: int | float | None,
    threshold: int | float | None,
) -> bool | None:
    if threshold is None:
        return None
    if value is None:
        return False
    return value <= threshold
