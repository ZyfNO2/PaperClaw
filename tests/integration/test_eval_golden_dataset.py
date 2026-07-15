from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.eval import EvalThresholds, evaluate_trace
from paperclaw.trace import TraceEvent, load_trace_jsonl

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "eval_golden"


class _Reader:
    def __init__(self, events: tuple[TraceEvent, ...]) -> None:
        self._events = events

    def get_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> tuple[TraceEvent, ...]:
        assert run_id == "run-golden"
        events = tuple(
            event for event in self._events if event.sequence > since_sequence
        )
        if require_terminal and not any(
            event.event_type
            in {"run.completed", "run.failed", "run.stopped", "run.cancelled"}
            for event in events
        ):
            raise ValueError("trace does not contain a terminal event")
        return events

    def iter_run_trace(self, run_id: str, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


def _scenarios() -> list[dict]:
    manifest = json.loads(
        (FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 1
    return manifest["scenarios"]


@pytest.mark.parametrize(
    "scenario",
    _scenarios(),
    ids=lambda scenario: scenario["name"],
)
def test_golden_eval_scenario_matches_frozen_expectations(
    scenario: dict,
) -> None:
    events = load_trace_jsonl(
        FIXTURE_ROOT / scenario["trace"],
        require_terminal=scenario["require_terminal"],
    )
    report = evaluate_trace(
        _Reader(events),
        "run-golden",
        thresholds=EvalThresholds(**scenario["thresholds"]),
        require_terminal=scenario["require_terminal"],
    )
    expected = scenario["expected"]
    metrics = {metric.name: metric.value for metric in report.metrics}

    assert report.overall_passed is expected["overall_passed"]
    assert list(report.failed_checks) == expected["failed_checks"]
    assert report.terminal_event == expected["terminal_event"]
    for name, value in expected["metrics"].items():
        assert metrics[name] == value


def test_golden_dataset_files_are_declared_once() -> None:
    scenarios = _scenarios()
    declared = [scenario["trace"] for scenario in scenarios]
    actual = sorted(path.name for path in FIXTURE_ROOT.glob("*.trace.jsonl"))

    assert len(declared) == len(set(declared))
    assert sorted(declared) == actual
