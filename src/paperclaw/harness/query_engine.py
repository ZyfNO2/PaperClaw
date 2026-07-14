"""Synchronous, single-conversation QueryEngine MVP.

This module is intentionally a thin façade. It creates and tracks runs,
forwards limits and stop requests to an injected executor, emits ordered
lifecycle events, and normalizes terminal results. It never executes tools,
opens SQLite, builds prompts, or retries side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, RLock
from typing import Callable
from uuid import uuid4

from .contracts import (
    RUNNING_STATUS,
    AgentRunView,
    ExecutionReport,
    RunExecutor,
    RunLimits,
    RunRequest,
    RunResult,
)

EventHandler = Callable[[str, dict], None]


class ExecutorContractError(RuntimeError):
    """Raised when an executor returns a result that violates run limits."""


class _CooperativeStopToken:
    def __init__(self) -> None:
        self._event = Event()
        self._reason: str | None = None
        self._lock = RLock()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def is_set(self) -> bool:
        """Compatibility with the existing AgentRuntime cancel_event shape."""
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def request(self, reason: str) -> bool:
        normalized = reason.strip()
        if not normalized:
            raise ValueError("stop reason must not be empty")
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = normalized
            self._event.set()
            return True


@dataclass
class _RunRecord:
    run_id: str
    conversation_id: str
    status: str
    limits: RunLimits
    stop_reason: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    last_event_sequence: int = 0
    terminal_emitted: bool = False

    def view(self) -> AgentRunView:
        return AgentRunView(
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            status=self.status,
            limits=self.limits,
            stop_reason=self.stop_reason,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            last_event_sequence=self.last_event_sequence,
        )


class QueryEngine:
    """Stable synchronous entry point for one sequential conversation.

    ``RunExecutor`` is injected so this façade remains independent of the
    concrete model, tools, PocketFlow graph, ContextBuilder, and SessionService.
    The v0.05 Phase-B adapter will connect those existing components without
    changing this public interface.
    """

    def __init__(
        self,
        executor: RunExecutor,
        *,
        conversation_id: str,
        event_handler: EventHandler | None = None,
    ) -> None:
        if not conversation_id.strip():
            raise ValueError("conversation_id must not be empty")
        self._executor = executor
        self._conversation_id = conversation_id
        self._event_handler = event_handler
        self._runs: dict[str, _RunRecord] = {}
        self._tokens: dict[str, _CooperativeStopToken] = {}
        self._active_run_id: str | None = None
        self._lock = RLock()

    def submit(self, text: str, *, limits: RunLimits | None = None) -> RunResult:
        """Execute one user submission and return a structured terminal result."""
        normalized = text.strip()
        if not normalized:
            raise ValueError("text must not be empty")
        resolved_limits = limits or RunLimits()

        with self._lock:
            if self._active_run_id is not None:
                raise RuntimeError(
                    "concurrent submit is outside the v0.05 MVP; "
                    f"active_run_id={self._active_run_id}"
                )
            run_id = f"run-{uuid4().hex[:12]}"
            record = _RunRecord(
                run_id=run_id,
                conversation_id=self._conversation_id,
                status=RUNNING_STATUS,
                limits=resolved_limits,
            )
            token = _CooperativeStopToken()
            self._runs[run_id] = record
            self._tokens[run_id] = token
            self._active_run_id = run_id

        self._emit(
            run_id,
            "run.started",
            {
                "conversation_id": self._conversation_id,
                "limits": {
                    "max_steps": resolved_limits.max_steps,
                    "max_model_calls": resolved_limits.max_model_calls,
                    "max_tool_calls": resolved_limits.max_tool_calls,
                },
            },
        )

        request = RunRequest(
            run_id=run_id,
            conversation_id=self._conversation_id,
            text=normalized,
            limits=resolved_limits,
        )

        error_payload: dict | None = None
        try:
            report = self._executor.execute(
                request,
                emit=lambda event_type, payload: self._emit(
                    run_id, event_type, payload
                ),
                stop_token=token,
            )
            self._validate_report(report, resolved_limits)
        except ExecutorContractError as exc:
            report = ExecutionReport(
                status="failed",
                output=None,
                stop_reason="executor_contract_violation",
            )
            error_payload = {
                "error_code": "EXECUTOR_CONTRACT_VIOLATION",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
            }
        except Exception as exc:  # runtime boundary: normalize, do not hide details
            report = ExecutionReport(
                status="failed",
                output=None,
                stop_reason="executor_failed",
            )
            error_payload = {
                "error_code": "EXECUTOR_FAILED",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
            }

        with self._lock:
            record = self._runs[run_id]
            record.status = report.status
            record.stop_reason = report.stop_reason
            record.model_calls = report.model_calls
            record.tool_calls = report.tool_calls

        self._emit_terminal(run_id, report, error_payload=error_payload)

        with self._lock:
            self._active_run_id = None
            self._tokens.pop(run_id, None)
            record = self._runs[run_id]
            return RunResult(
                run_id=record.run_id,
                status=record.status,
                output=report.output,
                stop_reason=record.stop_reason or "unknown",
                model_calls=record.model_calls,
                tool_calls=record.tool_calls,
                last_event_sequence=record.last_event_sequence,
            )

    def get_run(self, run_id: str) -> AgentRunView:
        """Return the current immutable view for a known run."""
        with self._lock:
            try:
                return self._runs[run_id].view()
            except KeyError as exc:
                raise KeyError(f"unknown run_id: {run_id}") from exc

    def request_stop(
        self,
        run_id: str,
        reason: str = "user_requested",
    ) -> bool:
        """Request cooperative stop; effect is executor-defined safe-boundary."""
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"unknown run_id: {run_id}")
            token = self._tokens.get(run_id)
            if token is None:
                return False
            accepted = token.request(reason)

        if accepted:
            self._emit(run_id, "run.stop_requested", {"reason": reason})
        return accepted

    def _validate_report(self, report: ExecutionReport, limits: RunLimits) -> None:
        if report.model_calls > limits.max_model_calls:
            raise ExecutorContractError(
                f"model_calls={report.model_calls} exceeds "
                f"max_model_calls={limits.max_model_calls}"
            )
        if report.tool_calls > limits.max_tool_calls:
            raise ExecutorContractError(
                f"tool_calls={report.tool_calls} exceeds "
                f"max_tool_calls={limits.max_tool_calls}"
            )

    def _emit(self, run_id: str, event_type: str, payload: dict) -> int:
        if not event_type:
            raise ValueError("event_type must not be empty")
        with self._lock:
            record = self._runs[run_id]
            record.last_event_sequence += 1
            sequence = record.last_event_sequence
        envelope = dict(payload)
        envelope.setdefault("run_id", run_id)
        envelope["sequence"] = sequence
        if self._event_handler is not None:
            try:
                self._event_handler(event_type, envelope)
            except Exception:
                # Event handlers are observers, not part of the run state machine.
                # A UI/logging callback must not strand the conversation in an
                # active state or change the executor's terminal result.
                pass
        return sequence

    def _emit_terminal(
        self,
        run_id: str,
        report: ExecutionReport,
        *,
        error_payload: dict | None,
    ) -> None:
        with self._lock:
            record = self._runs[run_id]
            if record.terminal_emitted:
                raise RuntimeError(f"terminal event already emitted for {run_id}")
            record.terminal_emitted = True

        if report.status == "completed":
            event_type = "run.completed"
        elif report.status == "failed":
            event_type = "run.failed"
        else:
            event_type = "run.stopped"

        payload = {
            "status": report.status,
            "stop_reason": report.stop_reason,
            "model_calls": report.model_calls,
            "tool_calls": report.tool_calls,
        }
        if error_payload:
            payload.update(error_payload)
        self._emit(run_id, event_type, payload)
