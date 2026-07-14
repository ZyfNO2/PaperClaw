from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from paperclaw.tools.base import ToolResult
from paperclaw.agent.verification import DoneProposal, ReflectionDecision, VerificationPlan, VerificationResult


@dataclass
class ToolCall:
    """A single validated tool invocation chosen by the model for the current step."""

    action: str
    arguments: dict[str, Any]
    reason: str


@dataclass
class HistoryEntry:
    """Serializable execution trace item used as both runtime memory and later replay/debug evidence."""

    step: int
    tool: str
    arguments: dict[str, Any]
    reason: str
    result: ToolResult

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def initial_state(
    task: str,
    workspace: Path,
    max_steps: int = 12,
    timeout_seconds: int = 0,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Create the smallest structured run state.

    The runtime keeps goal progress, tool evidence, and stop reasons here instead of overloading free-form dialogue
    history, which keeps later Context/Session work compatible with the same contract.
    ``run_id`` may be supplied by the v0.05 QueryEngine; legacy callers keep the
    existing generated identity.
    """

    import time as _time

    return {
        "run_id": run_id or f"run-{uuid4()}",
        "task": task,
        "workspace": workspace.resolve(strict=True),
        "history": [],
        "current_tool_call": None,
        "step_count": 0,
        "event_sequence": 0,
        "trace_events": [],
        "max_steps": max_steps,
        "timeout_seconds": timeout_seconds,
        "run_start_time": _time.monotonic(),
        "invalid_output_count": 0,
        "result": None,
        "verification": None,
        "verification_status": "unverified",
        "done_proposal": None,
        "verification_plan": None,
        "verification_result": None,
        "reflection_decision": None,
        "reflection_round_count": 0,
        "max_reflection_rounds": 2,
        "last_failure_signature": None,
        "failure_signature_count": 0,
        "remaining_issues": [],
        "stop_reason": None,
        "event_handler": None,
    }
