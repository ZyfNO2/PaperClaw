"""Production adapter from QueryEngine to the existing AgentRuntime.

The adapter is intentionally small. It wraps the existing model and tools to
apply per-run call budgets at the real invocation boundary, forwards structured
runtime events, optionally binds the run to the v0.04 SessionService, and
normalizes the existing shared state into an ExecutionReport.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from paperclaw.agent.flow import AgentRuntime, default_registry
from paperclaw.context.repository import Repository
from paperclaw.context.session import SessionService
from paperclaw.models.base import ChatModel, ModelTurn
from paperclaw.models.reliability import ProviderError
from paperclaw.tools.base import (
    ToolContext,
    ToolControlFlow,
    ToolResult,
    ToolValidationError,
)
from paperclaw.tools.registry import ToolRegistry
from paperclaw.trace.redaction import TraceRedactor

from .contracts import EventEmitter, ExecutionReport, RunLimits, RunRequest, StopToken

LegacyEventHandler = Callable[[str, dict], None]

_PROVIDER_METADATA_KEYS = frozenset(
    {
        "request_id",
        "finish_reason",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "attempt_count",
        "retry_count",
    }
)


class RunBudgetExhausted(RuntimeError):
    """Raised before a model call when its per-run budget is exhausted."""

    def __init__(self, resource: str) -> None:
        super().__init__(f"{resource} budget exhausted")
        self.resource = resource


class RunStopped(RuntimeError):
    """Raised when a stop request wins a race immediately before a model call."""


@dataclass
class _Usage:
    limits: RunLimits
    model_calls: int = 0
    tool_calls: int = 0


def _safe_model_metadata(model: ChatModel) -> dict[str, str]:
    """Return explicit non-secret identity without inventing model metadata.

    Test doubles and legacy model implementations that do not expose stable
    ``provider``/``model`` attributes retain their historical event shape.
    Production adapters may opt in by exposing either field.
    """

    metadata: dict[str, str] = {}
    provider = getattr(model, "provider", None)
    model_name = getattr(model, "model", None)
    if isinstance(provider, str) and provider.strip():
        metadata["provider"] = provider.strip()
    if isinstance(model_name, str) and model_name.strip():
        metadata["model"] = model_name.strip()
    return metadata


def _safe_turn_metadata(turn: ModelTurn) -> dict[str, Any]:
    """Allow only normalized scalar provider facts into runtime events."""

    result: dict[str, Any] = {}
    for key in _PROVIDER_METADATA_KEYS:
        value = turn.metadata.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            result[key] = value
        elif isinstance(value, str) and value.strip():
            result[key] = value.strip()[:200]
    return result


class _BudgetedModel:
    def __init__(
        self,
        model: ChatModel,
        usage: _Usage,
        emit: EventEmitter,
        stop_token: StopToken,
    ) -> None:
        self._model = model
        self._usage = usage
        self._emit = emit
        self._stop_token = stop_token
        self._metadata = _safe_model_metadata(model)

    def complete(self, prompt: str) -> ModelTurn:
        if self._stop_token.is_cancelled:
            raise RunStopped(self._stop_token.reason or "cancelled")
        if self._usage.model_calls >= self._usage.limits.max_model_calls:
            self._emit(
                "model.failed",
                {
                    **self._metadata,
                    "error_code": "MODEL_BUDGET_EXHAUSTED",
                    "limit": self._usage.limits.max_model_calls,
                },
            )
            raise RunBudgetExhausted("max_model_calls")

        self._usage.model_calls += 1
        call_index = self._usage.model_calls
        started_at = perf_counter()
        self._emit(
            "model.started",
            {**self._metadata, "call_index": call_index},
        )
        try:
            turn = self._model.complete(prompt)
        except Exception as exc:
            duration = (
                {"duration_ms": max(0, round((perf_counter() - started_at) * 1000))}
                if self._metadata
                else {}
            )
            provider_metadata = (
                exc.to_metadata() if isinstance(exc, ProviderError) else {}
            )
            error_code = (
                exc.code if isinstance(exc, ProviderError) else "MODEL_CALL_FAILED"
            )
            self._emit(
                "model.failed",
                {
                    **self._metadata,
                    "call_index": call_index,
                    **duration,
                    **provider_metadata,
                    "error_code": error_code,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                },
            )
            # The provider call crossed a cooperative-stop boundary while it
            # was already in flight. Cancellation owns this adapter-level
            # outcome, while the preceding model.failed event still preserves
            # the original sanitized failure for diagnostics.
            if self._stop_token.is_cancelled:
                raise RunStopped(self._stop_token.reason or "cancelled") from exc
            raise
        turn_metadata = _safe_turn_metadata(turn)
        duration = (
            {"duration_ms": max(0, round((perf_counter() - started_at) * 1000))}
            if self._metadata or turn_metadata
            else {}
        )
        self._emit(
            "model.completed",
            {
                **self._metadata,
                "call_index": call_index,
                **duration,
                **turn_metadata,
            },
        )
        return turn


class _BudgetedTool:
    """Tool wrapper that preserves the existing validate/execute path."""

    def __init__(
        self,
        tool: Any,
        usage: _Usage,
        emit: EventEmitter,
        stop_token: StopToken,
    ) -> None:
        self._tool = tool
        self._usage = usage
        self._emit = emit
        self._stop_token = stop_token
        self._call_index: int | None = None
        self.name = tool.name
        self.description = tool.description

    def validate(self, arguments: dict[str, Any]) -> None:
        self._call_index = None
        if self._stop_token.is_cancelled:
            raise ToolControlFlow(self._stop_token.reason or "cancelled")
        if self._usage.tool_calls >= self._usage.limits.max_tool_calls:
            self._emit(
                "tool.failed",
                {
                    "tool": self.name,
                    "error_code": "TOOL_BUDGET_EXHAUSTED",
                    "limit": self._usage.limits.max_tool_calls,
                },
            )
            raise ToolControlFlow("max_tool_calls")

        self._usage.tool_calls += 1
        self._call_index = self._usage.tool_calls
        self._emit(
            "tool.started",
            {"tool": self.name, "call_index": self._call_index},
        )
        try:
            self._tool.validate(arguments)
        except ToolValidationError as exc:
            denied = "denied" in str(exc).lower()
            self._emit(
                "permission.denied" if denied else "tool.failed",
                {
                    "tool": self.name,
                    "call_index": self._call_index,
                    "error_code": "PERMISSION_DENIED" if denied else "VALIDATION_ERROR",
                    "error_message": str(exc)[:500],
                },
            )
            raise
        except Exception as exc:
            self._emit(
                "tool.failed",
                {
                    "tool": self.name,
                    "call_index": self._call_index,
                    "error_code": "TOOL_VALIDATION_FAILED",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                },
            )
            # Match the provider boundary above without changing unrelated
            # runtime, session, or persistence exceptions into cancellations.
            if self._stop_token.is_cancelled:
                raise ToolControlFlow(
                    self._stop_token.reason or "cancelled"
                ) from exc
            raise

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        tool_context = ToolContext(
            workspace=context.workspace,
            output_limit=context.output_limit,
            stop_token=self._stop_token,
            remaining_model_calls=context.remaining_model_calls,
            remaining_tool_calls=context.remaining_tool_calls,
        )
        try:
            result = self._tool.execute(arguments, tool_context)
        except Exception as exc:
            self._emit(
                "tool.failed",
                {
                    "tool": self.name,
                    "call_index": self._call_index,
                    "error_code": "TOOL_EXECUTION_FAILED",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                },
            )
            # As with provider calls, an exception from a tool that was already
            # executing when a cooperative stop was accepted belongs to the
            # adapter cancellation boundary. Preserve the diagnostic event,
            # then translate only this in-flight tool outcome into control flow.
            if self._stop_token.is_cancelled:
                raise ToolControlFlow(
                    self._stop_token.reason or "cancelled"
                ) from exc
            raise

        self._emit(
            "tool.completed" if result.ok else "tool.failed",
            {
                "tool": self.name,
                "call_index": self._call_index,
                "ok": result.ok,
                "error_code": result.error_code,
            },
        )
        return result


class AgentRuntimeExecutor:
    """RunExecutor implementation backed by the existing synchronous runtime."""

    def __init__(
        self,
        model: ChatModel,
        workspace: Path | str,
        *,
        registry: ToolRegistry | None = None,
        enable_verification_gate: bool = True,
        repository: Repository | None = None,
        legacy_event_handler: LegacyEventHandler | None = None,
    ) -> None:
        self._model = model
        self._workspace = Path(workspace).resolve(strict=True)
        self._registry = registry or default_registry()
        self._enable_verification_gate = enable_verification_gate
        self._repository = repository
        self._legacy_event_handler = legacy_event_handler
        api_key = getattr(model, "api_key", "")
        self._event_redactor = TraceRedactor(
            secret_values=[api_key] if isinstance(api_key, str) else (),
        )
        self.last_state: dict[str, Any] | None = None

    def execute(
        self,
        request: RunRequest,
        *,
        emit: EventEmitter,
        stop_token: StopToken,
    ) -> ExecutionReport:
        usage = _Usage(request.limits)
        session = self._open_session(request)

        def runtime_emit(event_type: str, payload: dict) -> int:
            safe_payload = self._event_redactor.redact_payload(payload)
            sequence = emit(event_type, safe_payload)
            if session is not None:
                session.emit(
                    event_type,
                    {**safe_payload, "query_event_sequence": sequence},
                )
            return sequence

        model = _BudgetedModel(self._model, usage, runtime_emit, stop_token)
        tools = ToolRegistry(
            _BudgetedTool(
                self._registry.get(name),
                usage,
                runtime_emit,
                stop_token,
            )
            for name in self._registry.names
        )
        runtime = AgentRuntime(
            model,
            tools,
            enable_verification_gate=self._enable_verification_gate,
        )

        try:
            state = runtime.run(
                request.text,
                self._workspace,
                max_steps=request.limits.max_steps,
                event_handler=self._legacy_event_handler,
                cancel_event=stop_token,
                run_id=request.run_id,
            )
            self.last_state = state
            report = self._report_from_state(state, usage, stop_token)
        except RunBudgetExhausted as exc:
            self.last_state = runtime.last_state
            report = ExecutionReport(
                status="budget_exhausted",
                output=(runtime.last_state or {}).get("result"),
                stop_reason=exc.resource,
                model_calls=usage.model_calls,
                tool_calls=usage.tool_calls,
            )
        except ToolControlFlow as exc:
            self.last_state = runtime.last_state
            budget_stop = exc.reason == "max_tool_calls"
            report = ExecutionReport(
                status="budget_exhausted" if budget_stop else "stopped",
                output=(runtime.last_state or {}).get("result"),
                stop_reason=exc.reason,
                model_calls=usage.model_calls,
                tool_calls=usage.tool_calls,
            )
        except RunStopped:
            self.last_state = runtime.last_state
            report = ExecutionReport(
                status="stopped",
                output=(runtime.last_state or {}).get("result"),
                stop_reason=stop_token.reason or "cancelled",
                model_calls=usage.model_calls,
                tool_calls=usage.tool_calls,
            )
        except Exception:
            self.last_state = runtime.last_state
            # Adapter wrappers above own cancellation races. Everything that
            # reaches this catch-all remains a genuine runtime failure even if
            # a stop request happened concurrently, so session/persistence
            # faults are never hidden as successful cooperative cancellation.
            report = ExecutionReport(
                status="failed",
                output=(runtime.last_state or {}).get("result"),
                stop_reason="runtime_failed",
                model_calls=usage.model_calls,
                tool_calls=usage.tool_calls,
            )

        self._finish_session(session, report)
        return report

    def _open_session(self, request: RunRequest) -> SessionService | None:
        if self._repository is None:
            return None
        self._repository.create_conversation(
            request.conversation_id,
            metadata={"source": "query_engine"},
        )
        self._repository.start_run(
            run_id=request.run_id,
            conversation_id=request.conversation_id,
            agent_id="query_engine",
            role="agent",
            metadata={
                "max_steps": request.limits.max_steps,
                "max_model_calls": request.limits.max_model_calls,
                "max_tool_calls": request.limits.max_tool_calls,
            },
        )
        session = SessionService(
            self._repository,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            agent_id="query_engine",
        )
        # QueryEngine emits run.started before invoking this executor, so the
        # corresponding in-memory sequence is always 1. Persist that lifecycle
        # fact explicitly; all later adapter events preserve their actual
        # QueryEngine sequence through runtime_emit.
        session.emit(
            "run.started",
            {
                "query_event_sequence": 1,
                "conversation_id": request.conversation_id,
                "limits": {
                    "max_steps": request.limits.max_steps,
                    "max_model_calls": request.limits.max_model_calls,
                    "max_tool_calls": request.limits.max_tool_calls,
                },
            },
        )
        session.append_message("user", request.text)
        return session

    @staticmethod
    def _finish_session(
        session: SessionService | None,
        report: ExecutionReport,
    ) -> None:
        if session is None:
            return
        if report.output:
            session.append_message(
                "assistant",
                report.output,
                metadata={"status": report.status},
            )
        session.close(stop_reason=report.stop_reason)

    @staticmethod
    def _report_from_state(
        state: dict[str, Any],
        usage: _Usage,
        stop_token: StopToken,
    ) -> ExecutionReport:
        reason = state.get("stop_reason") or "runtime_finished_without_reason"
        if reason in {"done", "completed_verified"}:
            status = "completed"
        elif reason in {"max_steps", "max_model_calls", "max_tool_calls"}:
            status = "budget_exhausted"
        elif reason == "recovery_required":
            status = "blocked"
        elif reason in {"blocked_environment", "verification_failed"}:
            status = "blocked"
        elif reason in {"cancelled", "timeout"}:
            status = "stopped"
            if reason == "cancelled" and stop_token.reason:
                reason = stop_token.reason
        else:
            status = "failed"

        return ExecutionReport(
            status=status,
            output=state.get("result"),
            stop_reason=reason,
            model_calls=usage.model_calls,
            tool_calls=usage.tool_calls,
        )
