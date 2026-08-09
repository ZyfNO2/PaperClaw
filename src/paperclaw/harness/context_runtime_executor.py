"""Opt-in AgentRuntime adapter for v0.08 Context Orchestration.

The existing ``AgentRuntimeExecutor`` remains unchanged. This module composes it
with a model-boundary adapter so QueryEngine stays a thin façade and every
Provider call receives one deterministic ``PromptAssembly``.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
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
from paperclaw.context.contracts import ContextSnapshot
from paperclaw.context.session import SessionService
from paperclaw.context.source_registry import (
    ContextSourceRegistry,
    ContextSourceRegistrySnapshot,
)
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

    def __init__(
        self,
        model: ChatModel,
        orchestrator: ContextOrchestrator,
        source_snapshot: ContextSourceRegistrySnapshot | None = None,
    ) -> None:
        self._model = model
        self._orchestrator = orchestrator
        self._source_snapshot = source_snapshot
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
        source_trace = self._source_trace_payload()
        self._emit(
            context,
            "context.build.started",
            {
                "step_id": step_id,
                "policy_version": self._orchestrator.policy.policy_version,
                **source_trace,
            },
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
                    **source_trace,
                },
            )
            raise

        context.assemblies.append(assembly)
        payload = {
            "step_id": step_id,
            **assembly.trace.to_event_payload(),
            **source_trace,
        }
        self._emit(context, "context.assembly.completed", payload)
        snapshot = self._persist_snapshot(context, request, assembly, step_id)
        self._emit(
            context,
            "context.snapshot.persisted",
            {
                "context_snapshot_id": snapshot.snapshot_id,
                "model_call_id": snapshot.model_call_id,
                "policy_fingerprint": snapshot.policy_fingerprint,
                "input_tokens": snapshot.input_tokens,
                "selected_memory_ids": list(snapshot.selected_memory_ids),
                "omitted_counts": dict(snapshot.omitted_counts),
            },
        )
        return self._model.complete(assembly.prompt)

    def _persist_snapshot(
        self,
        context: _BoundAssemblyContext,
        request: ContextRequest,
        assembly: PromptAssembly,
        step_id: str,
    ) -> ContextSnapshot:
        """Persist the bounded manifest immediately before provider I/O."""
        selected_ids = tuple(
            item.candidate_id for item in assembly.trace.selected if item.selected
        )
        excluded = tuple(
            {
                "item_id": item.candidate_id,
                "exclusion_reason": item.reason,
            }
            for item in assembly.trace.excluded
        )
        omitted_counts: dict[str, int] = {}
        for item in assembly.trace.excluded:
            omitted_counts[item.reason] = omitted_counts.get(item.reason, 0) + 1
        selected_artifacts = tuple(
            item.candidate_id
            for item in assembly.trace.selected
            if item.candidate_id.startswith(("evidence:", "artifact:", "context:"))
        )
        selected_event_ids: list[str] = []
        compaction_summary_ref: str | None = None
        end_sequence = (
            context.repository.last_committed_sequence(request.run_id)
            if context.repository is not None
            else request.at_sequence
        )
        if context.repository is not None:
            selected_tool_calls = {
                item.candidate_id.removeprefix("tool-group:")
                for item in assembly.trace.selected
                if item.selected and item.candidate_id.startswith("tool-group:")
            }
            for event in context.repository.list_events(request.run_id):
                payload = event.payload
                call_id = payload.get("call_id") or payload.get("tool_call_id")
                tool_key = None
                if isinstance(payload.get("tool"), str) and payload.get("call_index") is not None:
                    tool_key = f"{payload['tool']}:{payload['call_index']}"
                if (
                    isinstance(call_id, str)
                    and call_id in selected_tool_calls
                ) or (tool_key is not None and tool_key in selected_tool_calls):
                    selected_event_ids.append(event.event_id)
                if event.event_type == "context.compaction.completed":
                    compaction_summary_ref = f"event:{event.event_id}"
        policy_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "policy_version": assembly.trace.policy_version,
                    "prompt_version": assembly.trace.prompt_version,
                    "assembly_fingerprint": assembly.fingerprint,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        snapshot = ContextSnapshot(
            snapshot_id=f"ctxsnap:{request.run_id}:{step_id}",
            run_id=request.run_id,
            agent_id="context_orchestrator",
            role=request.role,
            source_item_ids=selected_ids,
            excluded_items=excluded,
            rendered_hash=hashlib.sha256(
                assembly.prompt.encode("utf-8")
            ).hexdigest(),
            estimated_tokens=assembly.estimated_tokens,
            estimator="char4",
            created_sequence=end_sequence,
            task_id=request.task_id,
            session_id=request.conversation_id,
            model_call_id=step_id,
            system_prompt_hash=hashlib.sha256(
                (assembly.sections[0].content if assembly.sections else "").encode(
                    "utf-8"
                )
            ).hexdigest(),
            static_prefix_hash=assembly.fingerprint,
            selected_memory_ids=assembly.trace.memory_ids,
            selected_artifact_locators=selected_artifacts,
            selected_event_ids=tuple(selected_event_ids),
            event_range={"start": request.at_sequence, "end": end_sequence},
            compaction_summary_ref=compaction_summary_ref,
            omitted_counts=omitted_counts,
            input_tokens=assembly.estimated_tokens,
            policy_fingerprint=policy_fingerprint,
        )
        if context.repository is not None:
            existing = context.repository.get_snapshot(snapshot.snapshot_id)
            if existing is None:
                context.repository.insert_snapshot(snapshot)
            else:
                snapshot = existing
        return snapshot

    def _source_trace_payload(self) -> dict[str, Any]:
        snapshot = self._source_snapshot
        if snapshot is None:
            return {
                "context_source_registry_fingerprint": None,
                "context_source_count": 0,
            }
        return {
            "context_source_registry_fingerprint": snapshot.fingerprint,
            "context_source_count": len(snapshot.descriptors),
        }

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
        memory_service: Any | None = None,
        user_scope_id: str = "default-user",
        project_scope_id: str | None = None,
    ) -> None:
        if orchestrator is not None and context_source_registry is not None:
            raise ValueError(
                "orchestrator and context_source_registry are mutually exclusive"
            )
        self._workspace = Path(workspace).resolve(strict=True)
        self._repository = repository
        self.context_source_registry = context_source_registry
        self.context_source_snapshot: ContextSourceRegistrySnapshot | None = None
        if orchestrator is not None:
            self._orchestrator = orchestrator
        elif context_source_registry is not None:
            self.context_source_snapshot = context_source_registry.freeze()
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
        self._model = _ContextAwareModel(
            model,
            self._orchestrator,
            self.context_source_snapshot,
        )
        self._delegate = AgentRuntimeExecutor(
            self._model,
            self._workspace,
            registry=registry,
            enable_verification_gate=enable_verification_gate,
            repository=repository,
            legacy_event_handler=legacy_event_handler,
            memory_service=memory_service,
            user_scope_id=user_scope_id,
            project_scope_id=project_scope_id,
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
