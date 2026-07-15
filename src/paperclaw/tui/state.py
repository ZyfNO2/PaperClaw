"""Deterministic UI state reduction for ordered QueryEngine events.

The reducer is intentionally independent from Textual. It is the boundary that
prevents delayed or duplicated worker messages from rolling the visible run
state backwards.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

TERMINAL_EVENTS = frozenset({"run.completed", "run.failed", "run.stopped"})
KNOWN_TIMELINE_EVENTS = frozenset(
    {
        "run.started",
        "model.started",
        "model.completed",
        "model.failed",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "verification.completed",
        "permission.denied",
        "run.stop_requested",
        *TERMINAL_EVENTS,
    }
)


@dataclass(frozen=True)
class RunSnapshot:
    """Minimal visible state for the single active run."""

    run_id: str | None = None
    status: str = "idle"
    stop_reason: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    last_sequence: int = 0
    terminal: bool = False


@dataclass(frozen=True)
class ReducedEvent:
    """Outcome of applying one runtime event to the current snapshot."""

    accepted: bool
    snapshot: RunSnapshot
    timeline_text: str | None = None
    rejection_reason: str | None = None
    known_event: bool = True


class EventReducer:
    """Apply one monotonic event stream without allowing stale state rollback."""

    def __init__(self) -> None:
        self._snapshot = RunSnapshot()

    @property
    def snapshot(self) -> RunSnapshot:
        return self._snapshot

    def reset(self) -> RunSnapshot:
        self._snapshot = RunSnapshot()
        return self._snapshot

    def apply(self, event_type: str, payload: Mapping[str, Any]) -> ReducedEvent:
        run_id = payload.get("run_id")
        sequence = payload.get("sequence")
        if not isinstance(run_id, str) or not run_id.strip():
            return self._reject("missing run_id")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            return self._reject("invalid sequence")

        current = self._snapshot
        if current.run_id is not None and run_id != current.run_id:
            return self._reject("event belongs to another run")
        if sequence <= current.last_sequence:
            return self._reject("stale or duplicate sequence")
        if current.terminal:
            return self._reject("event arrived after terminal state")

        status = current.status
        stop_reason = current.stop_reason
        model_calls = current.model_calls
        tool_calls = current.tool_calls
        terminal = False

        if event_type == "run.started":
            status = "running"
        elif event_type == "run.stop_requested":
            status = "stopping"
            stop_reason = _optional_text(payload.get("reason")) or "user_requested"
        elif event_type == "model.started":
            model_calls = max(model_calls, _positive_int(payload.get("call_index")))
        elif event_type == "tool.started":
            tool_calls = max(tool_calls, _positive_int(payload.get("call_index")))
        elif event_type in TERMINAL_EVENTS:
            terminal = True
            status = _terminal_status(event_type, payload)
            stop_reason = _optional_text(payload.get("stop_reason"))
            model_calls = max(model_calls, _non_negative_int(payload.get("model_calls")))
            tool_calls = max(tool_calls, _non_negative_int(payload.get("tool_calls")))

        self._snapshot = RunSnapshot(
            run_id=run_id,
            status=status,
            stop_reason=stop_reason,
            model_calls=model_calls,
            tool_calls=tool_calls,
            last_sequence=sequence,
            terminal=terminal,
        )
        known = event_type in KNOWN_TIMELINE_EVENTS
        return ReducedEvent(
            accepted=True,
            snapshot=self._snapshot,
            timeline_text=format_timeline_event(event_type, payload),
            known_event=known,
        )

    def apply_result(
        self,
        *,
        run_id: str,
        status: str,
        stop_reason: str,
        model_calls: int,
        tool_calls: int,
        last_sequence: int,
    ) -> RunSnapshot:
        """Reconcile a RunResult if its terminal event could not be rendered.

        QueryEngine normally emits the terminal event before returning. This
        method is a defensive display fallback only; it never decreases an
        already observed sequence or call counter.
        """

        current = self._snapshot
        if current.run_id not in {None, run_id}:
            return current
        self._snapshot = replace(
            current,
            run_id=run_id,
            status=status,
            stop_reason=stop_reason,
            model_calls=max(current.model_calls, model_calls),
            tool_calls=max(current.tool_calls, tool_calls),
            last_sequence=max(current.last_sequence, last_sequence),
            terminal=True,
        )
        return self._snapshot

    def _reject(self, reason: str) -> ReducedEvent:
        return ReducedEvent(
            accepted=False,
            snapshot=self._snapshot,
            rejection_reason=reason,
        )


def format_timeline_event(event_type: str, payload: Mapping[str, Any]) -> str:
    """Create a compact, structured row without rendering hidden reasoning."""

    sequence = payload.get("sequence", "?")
    prefix = f"#{sequence} {event_type}"
    if event_type.startswith("model."):
        suffix = _parts(
            ("call", payload.get("call_index")),
            ("error", payload.get("error_code")),
        )
    elif event_type.startswith("tool.") or event_type == "permission.denied":
        suffix = _parts(
            ("tool", payload.get("tool")),
            ("call", payload.get("call_index")),
            ("error", payload.get("error_code")),
        )
    elif event_type == "verification.completed":
        result = payload.get("result")
        verification_status = result.get("status") if isinstance(result, Mapping) else None
        suffix = _parts(("status", verification_status or payload.get("status")),)
    elif event_type.startswith("run."):
        suffix = _parts(
            ("status", payload.get("status")),
            ("reason", payload.get("stop_reason") or payload.get("reason")),
        )
    else:
        # Unknown events remain visible by name and sequence, but arbitrary
        # payload fields are deliberately not rendered.
        suffix = ""
    return f"{prefix}{' · ' + suffix if suffix else ''}"


def _parts(*items: tuple[str, Any]) -> str:
    return " · ".join(
        f"{label}={value}"
        for label, value in items
        if value is not None and str(value) != ""
    )


def _terminal_status(event_type: str, payload: Mapping[str, Any]) -> str:
    explicit = _optional_text(payload.get("status"))
    if explicit:
        return explicit
    return {
        "run.completed": "completed",
        "run.failed": "failed",
        "run.stopped": "stopped",
    }[event_type]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 0
    return value


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
