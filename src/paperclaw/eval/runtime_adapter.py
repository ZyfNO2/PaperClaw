"""Runtime adapter boundary for offline recordings and existing durable traces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from paperclaw.trace import SQLiteTraceReader, TraceEvent, TraceReader, load_trace_jsonl

from .contracts import EvaluationCase


@dataclass(frozen=True)
class RuntimeExecution:
    run_id: str
    reader: TraceReader
    trace_source: str


class RuntimeAdapter(Protocol):
    def execute(self, case: EvaluationCase) -> RuntimeExecution: ...


class _StaticTraceReader:
    def __init__(self, events: tuple[TraceEvent, ...]) -> None:
        self.events = events

    def get_run_trace(self, run_id: str, *, since_sequence: int = 0, require_terminal: bool = False) -> tuple[TraceEvent, ...]:
        events = tuple(event for event in self.events if event.run_id == run_id and event.sequence > since_sequence)
        if not events:
            raise ValueError(f"run does not exist: {run_id}")
        if require_terminal and events[-1].event_type not in {"run.completed", "run.failed", "run.cancelled", "run.stopped", "gate.waiting_approval"}:
            raise ValueError("trace does not contain a terminal event")
        return events

    def iter_run_trace(self, run_id: str, *, since_sequence: int = 0, require_terminal: bool = False):
        yield from self.get_run_trace(run_id, since_sequence=since_sequence, require_terminal=require_terminal)


class RecordedTraceAdapter:
    """Deterministic offline adapter; recordings are observations, not fake approvals."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()

    def execute(self, case: EvaluationCase) -> RuntimeExecution:
        source = case.metadata.get("trace_fixture")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("offline case metadata.trace_fixture is required")
        path = (self.workspace / source).resolve()
        if not path.is_relative_to(self.workspace):
            raise ValueError("trace_fixture must remain inside workspace")
        events = load_trace_jsonl(path, require_terminal=False)
        run_ids = {event.run_id for event in events}
        if len(run_ids) != 1:
            raise ValueError("trace_fixture must contain exactly one run")
        run_id = next(iter(run_ids))
        return RuntimeExecution(run_id, _StaticTraceReader(events), str(path))


class DurableTraceAdapter:
    """Read a previously executed local/live/distributed run from the real Trace store."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)

    def execute(self, case: EvaluationCase) -> RuntimeExecution:
        run_id = case.metadata.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("metadata.run_id is required for durable trace evaluation")
        return RuntimeExecution(run_id.strip(), SQLiteTraceReader(self.database), str(self.database))


__all__ = ["DurableTraceAdapter", "RecordedTraceAdapter", "RuntimeAdapter", "RuntimeExecution"]
