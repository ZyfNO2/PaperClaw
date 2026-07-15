"""PaperClaw v0.07 durable trace read-side foundation."""

from .contracts import (
    TERMINAL_EVENT_TYPES,
    TRACE_SCHEMA_VERSION,
    TraceEvent,
    TraceIntegrityError,
    validate_trace,
)
from .exporter import TraceExportSummary, export_trace_jsonl, load_trace_jsonl
from .reader import (
    RepositoryTraceReader,
    TraceReader,
    project_events,
    project_session_event,
)
from .redaction import TraceRedactor

__all__ = [
    "RepositoryTraceReader",
    "TERMINAL_EVENT_TYPES",
    "TRACE_SCHEMA_VERSION",
    "TraceEvent",
    "TraceExportSummary",
    "TraceIntegrityError",
    "TraceReader",
    "TraceRedactor",
    "export_trace_jsonl",
    "load_trace_jsonl",
    "project_events",
    "project_session_event",
    "validate_trace",
]
