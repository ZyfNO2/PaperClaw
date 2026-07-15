"""Explicitly authorized live re-execution linked to a recorded source Run.

Live replay cannot recover the original prompt because v0.07 deliberately does
not persist prompts. Callers must provide a new explicit task. The source trace
is read-only; execution always creates a new Run through a supplied RunExecutor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any
from uuid import uuid4

from paperclaw.harness import QueryEngine, RunExecutor, RunLimits, RunResult
from paperclaw.trace import TraceReader

from .recorded import replay_recorded_trace

LIVE_REPLAY_CONFIRMATION = "LIVE_REPLAY_EXECUTES_EXTERNAL_ACTIONS"
MUTATING_TOOL_NAMES = frozenset({"file_write", "file_edit", "bash"})


class LiveReplayError(RuntimeError):
    """Raised before live execution when a safety or source gate fails."""


@dataclass(frozen=True)
class LiveReplayPolicy:
    enabled: bool = False
    confirmation: str = ""
    require_source_completed: bool = True
    require_recorded_faithful: bool = True
    allowed_tools: tuple[str, ...] = ()
    allow_mutating_tools: bool = False
    limits: RunLimits = field(default_factory=RunLimits)

    def validate(self) -> None:
        if not self.enabled:
            raise LiveReplayError("live replay is disabled by policy")
        if self.confirmation != LIVE_REPLAY_CONFIRMATION:
            raise LiveReplayError("live replay confirmation token is missing or invalid")
        normalized = tuple(tool.strip() for tool in self.allowed_tools if tool.strip())
        if len(normalized) != len(set(normalized)):
            raise LiveReplayError("allowed_tools contains duplicates")
        mutating = sorted(set(normalized) & MUTATING_TOOL_NAMES)
        if mutating and not self.allow_mutating_tools:
            raise LiveReplayError(
                "mutating tools require allow_mutating_tools: " + ", ".join(mutating)
            )


@dataclass(frozen=True)
class LiveReplayPlan:
    source_run_id: str
    source_terminal_event: str
    source_terminal_status: str | None
    conversation_id: str
    prompt_sha256: str
    prompt_chars: int
    allowed_tools: tuple[str, ...]
    limits: RunLimits
    _prompt: str = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_run_id": self.source_run_id,
            "source_terminal_event": self.source_terminal_event,
            "source_terminal_status": self.source_terminal_status,
            "conversation_id": self.conversation_id,
            "prompt_sha256": self.prompt_sha256,
            "prompt_chars": self.prompt_chars,
            "allowed_tools": list(self.allowed_tools),
            "limits": asdict(self.limits),
        }

    def durable_metadata(self) -> dict[str, Any]:
        return {
            "live_replay": True,
            "source_run_id": self.source_run_id,
            "source_terminal_event": self.source_terminal_event,
            "prompt_sha256": self.prompt_sha256,
            "allowed_tools": list(self.allowed_tools),
        }


@dataclass(frozen=True)
class LiveReplayResult:
    plan: LiveReplayPlan
    run_result: RunResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "run_result": asdict(self.run_result),
        }


def prepare_live_replay(
    reader: TraceReader,
    source_run_id: str,
    task: str,
    *,
    policy: LiveReplayPolicy,
) -> LiveReplayPlan:
    """Validate source and authorization without executing external behavior."""

    policy.validate()
    normalized_task = task.strip()
    if not normalized_task:
        raise LiveReplayError("live replay task must not be empty")
    if len(normalized_task) > 200_000:
        raise LiveReplayError("live replay task exceeds 200000 characters")

    replay = replay_recorded_trace(
        reader,
        source_run_id,
        require_terminal=True,
    )
    if policy.require_recorded_faithful and not replay.faithful:
        raise LiveReplayError("source trace failed recorded replay integrity")
    if replay.terminal_event is None:
        raise LiveReplayError("source trace has no terminal event")
    if policy.require_source_completed and replay.terminal_event != "run.completed":
        raise LiveReplayError(
            f"source run is not completed: {replay.terminal_event}"
        )

    allowed_tools = tuple(
        tool.strip() for tool in policy.allowed_tools if tool.strip()
    )
    digest = hashlib.sha256(normalized_task.encode("utf-8")).hexdigest()
    return LiveReplayPlan(
        source_run_id=source_run_id,
        source_terminal_event=replay.terminal_event,
        source_terminal_status=replay.terminal_status,
        conversation_id=(
            f"live-replay-{source_run_id[:12]}-{uuid4().hex[:10]}"
        ),
        prompt_sha256=digest,
        prompt_chars=len(normalized_task),
        allowed_tools=allowed_tools,
        limits=policy.limits,
        _prompt=normalized_task,
    )


def execute_live_replay(
    plan: LiveReplayPlan,
    executor: RunExecutor,
) -> LiveReplayResult:
    """Execute a prepared plan as a new QueryEngine Run."""

    result = QueryEngine(
        executor,
        conversation_id=plan.conversation_id,
    ).submit(plan._prompt, limits=plan.limits)
    return LiveReplayResult(plan=plan, run_result=result)
