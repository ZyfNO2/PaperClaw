"""Opt-in AgentRuntime adapter for v0.08 Context Orchestration.

The existing ``AgentRuntimeExecutor`` remains unchanged. This module composes it
with a model-boundary adapter so QueryEngine stays a thin façade and every
Provider call receives one deterministic ``PromptAssembly``.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from paperclaw.context.orchestration import (
    ContextAssemblyBudgetExhausted,
    ContextOrchestrator,
    ContextPolicy,
    ContextRequest,
    PromptAssembly,
)
from paperclaw.context.repository import Repository
from paperclaw.context.session import SessionService
from paperclaw.context.source_registry import ContextSourceRegistry
from paperclaw.models.base import ChatModel, ModelTurn
from paperclaw.tools.registry import ToolRegistry

from .agent_runtime_executor import AgentRuntimeExecutor
from .contracts import EventEmitter, ExecutionReport, RunRequest, StopToken


@dataclass
class _BoundAssemblyContext:
    request: RunRequest
    emit: EventEmitter
    workspace: str
    repository: Repository | None
    call_index: int = 0
    assemblies: list[PromptAssembly] = field(default_factory=list)
    budget_error: ContextAssemblyBudgetExhausted | None = None


_CURRENT_CONTEXT: ContextVar[_BoundAssemblyContext | None] = ContextVar(
    "paperclaw_context_assembly",
    default=None,
)


class _ContextAwareModel:
    """ChatModel wrapper that assembles Context immediately before Provider I/O."""

    def __init__(self, model: ChatModel, orchestrator: ContextOrchestrator) -> None:
        self._model = model
        self._orchestrator = orchestrator
        # Preserve explicit provider identity used by AgentRuntimeExecutor Trace.
        for name in ("provider", "model", "api_key"):
            value = getattr(model, name, None)
            if value is not None:
                setattr(self, name, value)

    @contextmanager
    def bind(self, context: _BoundAssemblyContext) -> Iterator[None]:
        token = _CURRENT_CONTEXT.set(context)
        try:
            yield
        finally:
            _CURRENT_CONTEXT.reset(token)

    def complete(self, prompt: str) -> ModelTurn:
        context = _CURRENT_CONTEXT.get()
        if context is None:
            # Defensive parity fallback for direct test usage outside an executor.
            return self._model.complete(prompt)

        context.call_index += 1
        step_id = f"model-{context.call_index}"
        at_sequence = 0
        if context.repository is not None:
            at_sequence = context.repository.last_committed_sequence(
                context.request.run_id
            )
        request = ContextRequest(
            run_id=context.request.run_id,
            conversation_id=context.request.conversation_id,
            step_id=step_id,
            raw_prompt=prompt,
            workspace=context.workspace,
            at_sequence=at_sequence,
        )
        try:
            assembly = self._orchestrator.assemble(request)
        except ContextAssemblyBudgetExhausted as exc:
            context.budget_error = exc
            self._emit(
                context,
                "context.assembly.failed",
                {
                    "step_id": step_id,
                    "error_code": "CONTEXT_BUDGET_EXHAUSTED",
                    "required_tokens": exc.required_tokens,
                    "available_tokens": exc.available_tokens,
                    "policy_version": self._orchestrator.policy.policy_version,
                },
            )
            raise

        context.assemblies.append(assembly)
        payload = {
            "step_id": step_id,
            **assembly.trace.to_event_payload(),
        }
        self._emit(context, "context.assembly.completed", payload)
        return self._model.complete(assembly.prompt)

    @staticmethod
    def _emit(
        context: _BoundAssemblyContext,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        query_sequence = context.emit(event_type, payload)
        if context.repository is None:
            return
        session = SessionService.reopen(
            context.repository,
            conversation_id=context.request.conversation_id,
            run_id=context.request.run_id,
            agent_id="context_orchestrator",
        )
        session.emit(
            event_type,
            {**payload, "query_event_sequence": query_sequence},
        )


class ContextOrchestratedAgentRuntimeExecutor:
    """RunExecutor that opts the existing single-Agent Runtime into v0.08.

    This is composition, not a QueryEngine fork. The old
    ``AgentRuntimeExecutor`` remains available and behavior-compatible.
    """

    def __init__(
        self,
        model: ChatModel,
        workspace: Path | str,
        *,
        registry: ToolRegistry | None = None,
        enable_verification_gate: bool = True,
        repository: Repository | None = None,
        legacy_event_handler: Any | None = None,
        context_policy: ContextPolicy | None = None,
        orchestrator: ContextOrchestrator | None = None,
        context_source_registry: ContextSourceRegistry | None = None,
    ) -> None:
        if orchestrator is not None and context_source_registry is not None:
            raise ValueError(
                "orchestrator and context_source_registry are mutually exclusive"
            )
        self._workspace = Path(workspace).resolve(strict=True)
        self._repository = repository
        self.context_source_registry = context_source_registry
        if orchestrator is not None:
            self._orchestrator = orchestrator
        elif context_source_registry is not None:
            context_source_registry.freeze()
            self._orchestrator = ContextOrchestrator(
                repository,
                policy=context_policy,
                sources=(context_source_registry,),
            )
        else:
            self._orchestrator = ContextOrchestrator(
                repository,
                policy=context_policy,
            )
        self._model = _ContextAwareModel(model, self._orchestrator)
        self._delegate = AgentRuntimeExecutor(
            self._model,
            self._workspace,
            registry=registry,
            enable_verification_gate=enable_verification_gate,
            repository=repository,
            legacy_event_handler=legacy_event_handler,
        )
        self.last_state: dict[str, Any] | None = None
        self.last_assemblies: tuple[PromptAssembly, ...] = ()

    def execute(
        self,
        request: RunRequest,
        *,
        emit: EventEmitter,
        stop_token: StopToken,
    ) -> ExecutionReport:
        bound = _BoundAssemblyContext(
            request=request,
            emit=emit,
            workspace=str(self._workspace),
            repository=self._repository,
        )
        with self._model.bind(bound):
            report = self._delegate.execute(
                request,
                emit=emit,
                stop_token=stop_token,
            )
        self.last_state = self._delegate.last_state
        self.last_assemblies = tuple(bound.assemblies)

        # AgentRuntimeExecutor deliberately classifies unknown model-boundary
        # exceptions as failed. Reclassify only our explicit fail-closed budget
        # error; all other persistence/runtime failures remain genuine failures.
        if bound.budget_error is not None and report.status == "failed":
            return ExecutionReport(
                status="budget_exhausted",
                output=report.output,
                stop_reason="context_budget_exhausted",
                model_calls=report.model_calls,
                tool_calls=report.tool_calls,
            )
        return report


__all__ = ["ContextOrchestratedAgentRuntimeExecutor"]
