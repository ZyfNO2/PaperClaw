from __future__ import annotations

import json

import pytest

from paperclaw.context.contracts import SessionEvent
from paperclaw.trace import (
    TraceIntegrityError,
    TraceRedactor,
    project_events,
    validate_trace,
)


def _event(sequence: int, event_type: str, payload: dict) -> SessionEvent:
    return SessionEvent(
        event_id=f"evt-{sequence}",
        conversation_id="conv-trace",
        run_id="run-trace",
        sequence=sequence,
        event_type=event_type,
        payload={"schema_version": 1, **payload},
        created_at=f"2026-07-16T00:00:0{sequence}+00:00",
    )


def test_projection_is_versioned_bounded_and_redacted() -> None:
    secret = "mistral-secret-value"
    events = project_events(
        [
            _event(
                1,
                "model.started",
                {
                    "provider": "mistral",
                    "model": "test-model",
                    "latency_ms": 12.6,
                    "api_key": secret,
                    "authorization": f"Bearer {secret}",
                    "input_tokens": 123,
                    "path": "/home/alice/work/PaperClaw",
                    "nested": {"access_token": secret},
                },
            ),
            _event(2, "flow.stopped", {"stop_reason": "done"}),
        ],
        redactor=TraceRedactor(secret_values=[secret]),
        require_terminal=True,
    )

    assert [event.sequence for event in events] == [1, 2]
    assert events[0].schema_version == 1
    assert events[0].component == "model"
    assert events[0].status == "started"
    assert events[0].provider == "mistral"
    assert events[0].model == "test-model"
    assert events[0].duration_ms == 13
    assert events[0].payload["input_tokens"] == 123
    assert events[0].payload["api_key"] == "<REDACTED>"
    assert events[0].payload["authorization"] == "<REDACTED>"
    assert events[0].payload["nested"]["access_token"] == "<REDACTED>"
    assert events[0].payload["path"].startswith("<HOME>")

    serialized = json.dumps([event.to_dict() for event in events])
    assert secret not in serialized


def test_trace_rejects_events_after_terminal() -> None:
    events = project_events(
        [
            _event(1, "flow.stopped", {"stop_reason": "done"}),
        ],
        require_terminal=True,
    )
    late = events[0].__class__(
        event_id="evt-late",
        sequence=2,
        occurred_at="2026-07-16T00:00:02+00:00",
        conversation_id="conv-trace",
        run_id="run-trace",
        event_type="tool.started",
        component="tool",
    )

    with pytest.raises(TraceIntegrityError, match="after terminal"):
        validate_trace([*events, late])


def test_trace_rejects_non_monotonic_sequence() -> None:
    events = project_events(
        [
            _event(1, "model.started", {}),
            _event(2, "flow.stopped", {"stop_reason": "done"}),
        ]
    )

    with pytest.raises(TraceIntegrityError, match="strictly increasing"):
        validate_trace([events[1], events[0]])
