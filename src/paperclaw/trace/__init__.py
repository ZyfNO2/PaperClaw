"""PaperClaw v0.07 durable trace read-side foundation."""

from .contracts import (
    TERMINAL_EVENT_TYPES,
    TRACE_SCHEMA_VERSION,
    TraceEvent,
    TraceIntegrityError,
    validate_trace,
)
from .exporter import TraceExportSummary, export_trace_jsonl, load_trace_jsonl
from .inspector import (
    TimelineEntry,
    TraceInspection,
    inspect_run_trace,
    render_inspection_text,
)
from .reader import (
    RepositoryTraceReader,
    SQLiteTraceReader,
    TraceReadError,
    TraceReader,
    project_events,
    project_session_event,
)
from .redaction import TraceRedactor

__all__ = [
    "RepositoryTraceReader",
    "SQLiteTraceReader",
    "TERMINAL_EVENT_TYPES",
    "TRACE_SCHEMA_VERSION",
    "TimelineEntry",
    "TraceEvent",
    "TraceExportSummary",
    "TraceInspection",
    "TraceIntegrityError",
    "TraceReadError",
    "TraceReader",
    "TraceRedactor",
    "export_trace_jsonl",
    "inspect_run_trace",
    "load_trace_jsonl",
    "project_events",
    "project_session_event",
    "render_inspection_text",
    "validate_trace",
]
