from __future__ import annotations

import json

from hypothesis import given, settings, strategies as st

from paperclaw.eval import EvalThresholds, evaluate_trace
from paperclaw.replay import replay_recorded_trace
from paperclaw.trace import (
    TraceEvent,
    TraceIntegrityError,
    TraceRedactor,
    inspect_run_trace,
    validate_trace,
)


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
        assert run_id == "run-property"
        events = tuple(
            event for event in self._events if event.sequence > since_sequence
        )
        if require_terminal:
            validate_trace(events, require_terminal=True)
        return events

    def iter_run_trace(self, run_id: str, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


def _event(
    sequence: int,
    event_type: str,
    *,
    component: str,
    status: str | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    payload: dict | None = None,
) -> TraceEvent:
    return TraceEvent(
        event_id=f"evt-{sequence}",
        sequence=sequence,
        occurred_at=f"2026-07-16T00:00:{sequence:02d}+00:00",
        conversation_id="conv-property",
        run_id="run-property",
        event_type=event_type,
        component=component,
        status=status,
        duration_ms=duration_ms,
        error_code=error_code,
        payload=payload or {},
    )


@settings(max_examples=100, deadline=None)
@given(
    model_calls=st.integers(min_value=0, max_value=5),
    tool_calls=st.integers(min_value=0, max_value=5),
    retry_count=st.integers(min_value=0, max_value=4),
    duration_ms=st.integers(min_value=0, max_value=10_000),
    input_tokens=st.integers(min_value=0, max_value=100_000),
    output_tokens=st.integers(min_value=0, max_value=100_000),
)
def test_generated_valid_trace_is_deterministic_across_consumers(
    model_calls: int,
    tool_calls: int,
    retry_count: int,
    duration_ms: int,
    input_tokens: int,
    output_tokens: int,
) -> None:
    events: list[TraceEvent] = []
    sequence = 1
    events.append(_event(sequence, "run.started", component="harness", status="started"))
    sequence += 1

    for call_index in range(1, model_calls + 1):
        events.append(
            _event(
                sequence,
                "model.started",
                component="model",
                status="started",
                payload={"call_index": call_index},
            )
        )
        sequence += 1
        events.append(
            _event(
                sequence,
                "model.completed",
                component="model",
                status="completed",
                duration_ms=duration_ms,
                payload={
                    "call_index": call_index,
                    "retry_count": retry_count,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
            )
        )
        sequence += 1

    for call_index in range(1, tool_calls + 1):
        events.append(
            _event(
                sequence,
                "tool.started",
                component="tool",
                status="started",
                payload={"call_index": call_index, "tool": "fake_tool"},
            )
        )
        sequence += 1
        events.append(
            _event(
                sequence,
                "tool.completed",
                component="tool",
                status="completed",
                duration_ms=duration_ms,
                payload={
                    "call_index": call_index,
                    "tool": "fake_tool",
                    "ok": True,
                },
            )
        )
        sequence += 1

    events.append(
        _event(sequence, "run.completed", component="harness", status="completed")
    )
    snapshot = validate_trace(events, require_terminal=True)
    reader = _Reader(snapshot)

    replay_one = replay_recorded_trace(reader, "run-property")
    replay_two = replay_recorded_trace(reader, "run-property")
    inspection_one = inspect_run_trace(reader, "run-property")
    inspection_two = inspect_run_trace(reader, "run-property")
    eval_one = evaluate_trace(
        reader,
        "run-property",
        thresholds=EvalThresholds(require_completed=True),
    )
    eval_two = evaluate_trace(
        reader,
        "run-property",
        thresholds=EvalThresholds(require_completed=True),
    )

    assert replay_one.faithful is True
    assert replay_one.to_dict() == replay_two.to_dict()
    assert inspection_one.to_dict() == inspection_two.to_dict()
    assert eval_one.to_dict() == eval_two.to_dict()
    assert inspection_one.model_calls == model_calls
    assert inspection_one.tool_calls == tool_calls
    assert eval_one.overall_passed is True


@settings(max_examples=100, deadline=None)
@given(
    secret=st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
            min_codepoint=48,
            max_codepoint=122,
        ),
        min_size=8,
        max_size=40,
    )
)
def test_generated_secret_never_survives_redaction(secret: str) -> None:
    redactor = TraceRedactor(secret_values=[secret])
    payload = {
        "api_key": secret,
        "authorization": f"Bearer {secret}",
        "nested": {
            "client_secret": secret,
            "message": f"provider rejected key {secret}",
        },
        "prompt": f"private prompt {secret}",
    }

    redacted = redactor.redact_payload(payload)
    encoded = json.dumps(redacted, ensure_ascii=False, sort_keys=True)

    assert secret not in encoded
    assert redacted["api_key"] == "<REDACTED>"
    assert redacted["authorization"] == "<REDACTED>"
    assert redacted["prompt"]["redacted"] is True


@settings(max_examples=150, deadline=None)
@given(sequences=st.lists(st.integers(min_value=1, max_value=30), min_size=2, max_size=12))
def test_sequence_validator_accepts_only_strictly_increasing_inputs(
    sequences: list[int],
) -> None:
    events = tuple(
        _event(sequence, "model.started", component="model")
        for sequence in sequences
    )
    strictly_increasing = all(
        current > previous
        for previous, current in zip(sequences, sequences[1:])
    )

    if strictly_increasing:
        assert validate_trace(events) == events
    else:
        try:
            validate_trace(events)
        except TraceIntegrityError:
            pass
        else:
            raise AssertionError(
                "non-increasing sequence unexpectedly passed validation"
            )
