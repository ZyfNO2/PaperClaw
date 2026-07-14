"""Stable contracts for the v0.05 QueryEngine façade.

The harness deliberately owns only run lifecycle metadata. Model, tool,
context, session, and persistence behavior remain behind ``RunExecutor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

RUNNING_STATUS = "running"
TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "blocked", "stopped", "budget_exhausted"}
)


@dataclass(frozen=True)
class RunLimits:
    """Hard per-submit limits understood by the executor."""

    max_steps: int = 20
    max_model_calls: int = 10
    max_tool_calls: int = 20

    def __post_init__(self) -> None:
        for name, value in (
            ("max_steps", self.max_steps),
            ("max_model_calls", self.max_model_calls),
            ("max_tool_calls", self.max_tool_calls),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class RunRequest:
    """One normalized user submission passed to a runtime adapter."""

    run_id: str
    conversation_id: str
    text: str
    limits: RunLimits


@dataclass(frozen=True)
class ExecutionReport:
    """Terminal executor output consumed by ``QueryEngine``.

    Executors must return one terminal status and truthful call counters. The
    QueryEngine does not infer success from free-form output.
    """

    status: str
    output: str | None
    stop_reason: str
    model_calls: int = 0
    tool_calls: int = 0

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {self.status}")
        if not self.stop_reason:
            raise ValueError("stop_reason must not be empty")
        if self.model_calls < 0 or self.tool_calls < 0:
            raise ValueError("call counters must not be negative")


@dataclass(frozen=True)
class RunResult:
    """Public terminal result returned by ``QueryEngine.submit``."""

    run_id: str
    status: str
    output: str | None
    stop_reason: str
    model_calls: int
    tool_calls: int
    last_event_sequence: int


@dataclass(frozen=True)
class AgentRunView:
    """Read-only snapshot returned by ``QueryEngine.get_run``."""

    run_id: str
    conversation_id: str
    status: str
    limits: RunLimits
    stop_reason: str | None
    model_calls: int
    tool_calls: int
    last_event_sequence: int


EventEmitter = Callable[[str, dict], int]


class StopToken(Protocol):
    """Minimal cooperative-stop contract exposed to executors."""

    @property
    def is_cancelled(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...


class RunExecutor(Protocol):
    """Adapter boundary between QueryEngine and the existing runtime."""

    def execute(
        self,
        request: RunRequest,
        *,
        emit: EventEmitter,
        stop_token: StopToken,
    ) -> ExecutionReport: ...
