"""Side-effect-free replay of already-recorded TraceEvent control flow.

This module has no model, tool, workspace, repository-write, subprocess, or
network dependency. It re-applies immutable TraceEvent facts to a small state
machine and reports lifecycle inconsistencies; it cannot re-execute a Run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from paperclaw.trace import TERMINAL_EVENT_TYPES, TraceEvent, TraceReader

ReplaySeverity = Literal["warning", "error"]


class RecordedReplayError(ValueError):
    """Raised when strict recorded replay encounters an error-level issue."""


@dataclass(frozen=True)
class ReplayIssue:
    code: str
    severity: ReplaySeverity
    sequence: int | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReplayFrame:
    sequence: int
    event_type: str
    run_status: str
    active_model_calls: int
    active_tool_calls: int
    retry_count: int
    error_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecordedReplayResult:
    run_id: str
    conversation_id: str
    event_count: int
    applied_event_count: int
    terminal_event: str | None
    terminal_status: str | None
    faithful: bool
    issue_count: int
    issues: tuple[ReplayIssue, ...]
    frames: tuple[ReplayFrame, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [issue.to_dict() for issue in self.issues]
        data["frames"] = [frame.to_dict() for frame in self.frames]
        return data


def replay_recorded_trace(
    reader: TraceReader,
    run_id: str,
    *,
    require_terminal: bool = True,
    strict: bool = False,
    max_frames: int | None = None,
) -> RecordedReplayResult:
    """Replay recorded control flow without executing external behavior."""

    if max_frames is not None and max_frames <= 0:
        raise ValueError("max_frames must be positive")
    events = reader.get_run_trace(run_id, require_terminal=require_terminal)
    issues: list[ReplayIssue] = []
    frames: list[ReplayFrame] = []
    active_models: dict[str, int] = {}
    active_tools: dict[str, int] = {}
    run_started = False
    terminal: TraceEvent | None = None
    retry_count = 0
    error_count = 0
    run_status = "created"

    if events and events[0].event_type != "run.started":
        issues.append(
            ReplayIssue(
                code="RUN_START_NOT_RECORDED",
                severity="warning",
                sequence=events[0].sequence,
                message="trace predates or omits durable run.started",
            )
        )

    for event in events:
        if terminal is not None:
            issues.append(
                ReplayIssue(
                    code="EVENT_AFTER_TERMINAL",
                    severity="error",
                    sequence=event.sequence,
                    message=f"{event.event_type} appears after {terminal.event_type}",
                )
            )
            continue

        if event.event_type == "run.started":
            if run_started:
                issues.append(
                    ReplayIssue(
                        code="DUPLICATE_RUN_START",
                        severity="error",
                        sequence=event.sequence,
                        message="run.started was recorded more than once",
                    )
                )
            run_started = True
            run_status = "running"
        elif event.event_type == "model.started":
            _start_call(active_models, event, "model", issues)
        elif event.event_type in {"model.completed", "model.failed"}:
            _finish_call(active_models, event, "model", issues)
        elif event.event_type == "tool.started":
            _start_call(active_tools, event, "tool", issues)
        elif event.event_type in {
            "tool.completed",
            "tool.failed",
            "permission.denied",
        }:
            _finish_call(active_tools, event, "tool", issues)

        retry_count += _non_negative_int(event.payload.get("retry_count"))
        if _is_error(event):
            error_count += 1

        if event.event_type in TERMINAL_EVENT_TYPES:
            terminal = event
            run_status = event.status or event.event_type.rsplit(".", 1)[-1]
            if active_models:
                issues.append(
                    ReplayIssue(
                        code="MODEL_CALL_OPEN_AT_TERMINAL",
                        severity="error",
                        sequence=event.sequence,
                        message=(
                            f"terminal recorded with {len(active_models)} active "
                            "model call(s)"
                        ),
                    )
                )
            if active_tools:
                issues.append(
                    ReplayIssue(
                        code="TOOL_CALL_OPEN_AT_TERMINAL",
                        severity="error",
                        sequence=event.sequence,
                        message=(
                            f"terminal recorded with {len(active_tools)} active "
                            "tool call(s)"
                        ),
                    )
                )

        if max_frames is None or len(frames) < max_frames:
            frames.append(
                ReplayFrame(
                    sequence=event.sequence,
                    event_type=event.event_type,
                    run_status=run_status,
                    active_model_calls=len(active_models),
                    active_tool_calls=len(active_tools),
                    retry_count=retry_count,
                    error_count=error_count,
                )
            )

    if require_terminal and terminal is None:
        issues.append(
            ReplayIssue(
                code="TERMINAL_NOT_RECORDED",
                severity="error",
                sequence=events[-1].sequence if events else None,
                message="recorded replay requires a terminal event",
            )
        )

    faithful = not any(issue.severity == "error" for issue in issues)
    if strict and not faithful:
        summary = "; ".join(
            f"{issue.code}@{issue.sequence}" for issue in issues if issue.severity == "error"
        )
        raise RecordedReplayError(f"recorded replay integrity failed: {summary}")

    return RecordedReplayResult(
        run_id=events[0].run_id if events else run_id,
        conversation_id=events[0].conversation_id if events else "",
        event_count=len(events),
        applied_event_count=len(events),
        terminal_event=terminal.event_type if terminal else None,
        terminal_status=terminal.status if terminal else None,
        faithful=faithful,
        issue_count=len(issues),
        issues=tuple(issues),
        frames=tuple(frames),
    )


def render_recorded_replay_text(result: RecordedReplayResult) -> str:
    lines = [
        f"Recorded replay: {result.run_id}",
        f"Events applied: {result.applied_event_count}/{result.event_count}",
        (
            "Terminal: "
            f"{result.terminal_event or '-'} ({result.terminal_status or '-'})"
        ),
        f"Faithful: {'yes' if result.faithful else 'no'}",
        f"Issues: {result.issue_count}",
        "",
        "Frames:",
    ]
    for frame in result.frames:
        lines.append(
            f"{frame.sequence:>4} {frame.event_type} "
            f"status={frame.run_status} "
            f"model_active={frame.active_model_calls} "
            f"tool_active={frame.active_tool_calls} "
            f"retries={frame.retry_count} errors={frame.error_count}"
        )
    if result.issues:
        lines.extend(["", "Issues:"])
        for issue in result.issues:
            lines.append(
                f"{issue.severity.upper()} {issue.code}@{issue.sequence}: "
                f"{issue.message}"
            )
    return "\n".join(lines)


def _start_call(
    active: dict[str, int],
    event: TraceEvent,
    kind: str,
    issues: list[ReplayIssue],
) -> None:
    key = _call_key(event)
    if key in active:
        issues.append(
            ReplayIssue(
                code=f"DUPLICATE_{kind.upper()}_CALL_START",
                severity="error",
                sequence=event.sequence,
                message=f"{kind} call {key} started while already active",
            )
        )
    active[key] = event.sequence


def _finish_call(
    active: dict[str, int],
    event: TraceEvent,
    kind: str,
    issues: list[ReplayIssue],
) -> None:
    key = _explicit_call_key(event)
    if key is not None and key in active:
        active.pop(key)
        return
    if key is None and active:
        oldest = min(active, key=active.get)
        active.pop(oldest)
        return
    if _is_prestart_failure(event):
        return
    issues.append(
        ReplayIssue(
            code=f"UNMATCHED_{kind.upper()}_CALL_END",
            severity="error",
            sequence=event.sequence,
            message=f"{event.event_type} has no matching {kind}.started",
        )
    )


def _call_key(event: TraceEvent) -> str:
    return _explicit_call_key(event) or f"sequence:{event.sequence}"


def _explicit_call_key(event: TraceEvent) -> str | None:
    value = event.payload.get("call_index")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, str)) and str(value).strip():
        return str(value).strip()
    return None


def _is_prestart_failure(event: TraceEvent) -> bool:
    error_code = event.error_code or event.payload.get("error_code")
    return isinstance(error_code, str) and error_code.endswith("BUDGET_EXHAUSTED")


def _is_error(event: TraceEvent) -> bool:
    return bool(
        event.error_code
        or event.event_type.endswith((".failed", ".denied", ".blocked"))
        or event.status in {"failed", "denied", "blocked"}
    )


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return 0
