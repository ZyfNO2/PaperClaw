"""Worker agent runtime.

A Worker runs exactly one AgentTask using a scoped view of the world: limited
tools, limited paths, and bounded steps. It wraps the existing v0.02 AgentRuntime
so Verify / Reflection remain available without modification.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from paperclaw.agent.flow import AgentRuntime
from paperclaw.agent.verification import VerificationResult
from paperclaw.models.base import ChatModel
from paperclaw.multiagent.contracts import (
    AgentTask,
    MessageType,
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.events import emit_team_event
from paperclaw.multiagent.lease import LeaseManager
from paperclaw.multiagent.permissions import PermissionGuardLite
from paperclaw.multiagent.scoped_tools import WorkerRuntimeCounters, build_scoped_registry


class Worker:
    """Execute one task inside a scoped runtime.

    The Worker does not own global completion and cannot create sub-agents. It
    produces a WorkerResult that the Coordinator consumes.
    """

    def __init__(
        self,
        agent_id: str,
        model: ChatModel,
        guard: PermissionGuardLite,
        lease_manager: LeaseManager,
        team_state: dict,
        enable_verification_gate: bool = True,
    ) -> None:
        self.agent_id = agent_id
        self._model = model
        self._guard = guard
        self._lease_manager = lease_manager
        self._team_state = team_state
        self._enable_verification_gate = enable_verification_gate
        self._cancel_event = threading.Event()

    def run(self, task: AgentTask, workspace: Path) -> WorkerResult:
        """Run a single task to completion, failure, or cancellation."""

        emit_team_event(
            self._team_state,
            MessageType.TASK_ASSIGNED.value,
            self.agent_id,
            task.task_id,
            title=task.title,
            objective=task.objective,
        )

        counters = WorkerRuntimeCounters()
        runtime_state = self._make_worker_runtime_state(task, workspace)
        registry = build_scoped_registry(
            task,
            self._guard,
            self._lease_manager,
            self.agent_id,
            runtime_state,
            counters,
        )

        runtime = AgentRuntime(
            self._model,
            registry,
            enable_verification_gate=self._enable_verification_gate,
        )

        try:
            final_state = runtime.run(
                task.objective,
                workspace,
                max_steps=task.max_steps,
                event_handler=lambda event, payload: self._on_runtime_event(
                    event, payload, task.task_id, counters
                ),
                cancel_event=self._cancel_event,
            )
        except Exception as exc:  # defensive: single Worker failure must not crash Coordinator
            self._lease_manager.release_all_for_task(task.task_id)
            return WorkerResult(
                task_id=task.task_id,
                status=WorkerStatus.FAILED,
                summary=f"Worker crashed: {type(exc).__name__}: {exc}",
                unresolved_items=["internal worker error"],
            )

        status = self._derive_worker_status(final_state)
        changed_files = self._extract_changed_files(final_state)
        verification_result = final_state.get("verification_result")
        if not isinstance(verification_result, VerificationResult):
            verification_result = None

        # Local Verify is required: if gate is on and verification failed, the
        # Worker cannot report completed.
        if (
            self._enable_verification_gate
            and status == WorkerStatus.COMPLETED
            and verification_result is not None
            and verification_result.status != "passed"
        ):
            status = WorkerStatus.FAILED

        emit_team_event(
            self._team_state,
            MessageType.TASK_COMPLETED.value if status == WorkerStatus.COMPLETED else MessageType.TASK_FAILED.value,
            self.agent_id,
            task.task_id,
            status=status.value if isinstance(status, WorkerStatus) else status,
            changed_files=changed_files,
        )

        self._lease_manager.release_all_for_task(task.task_id)
        return WorkerResult(
            task_id=task.task_id,
            status=status,
            summary=final_state.get("result") or final_state.get("stop_reason") or "no result",
            changed_files=changed_files,
            verification_result=verification_result,
            unresolved_items=final_state.get("remaining_issues", []),
            handoff_notes=[f"steps={final_state.get('step_count', 0)}"],
            step_count=final_state.get("step_count", 0),
            model_call_count=counters.model_call_count,
            tool_call_count=counters.tool_call_count,
        )

    def cancel(self, task: AgentTask) -> WorkerResult:
        """Signal cancellation and release leases so the Worker stops cleanly."""

        self._cancel_event.set()
        self._lease_manager.release_all_for_task(task.task_id)
        emit_team_event(
            self._team_state,
            MessageType.TASK_BLOCKED.value,
            self.agent_id,
            task.task_id,
            reason="cancelled",
        )
        return WorkerResult(
            task_id=task.task_id,
            status=WorkerStatus.CANCELLED,
            summary="cancelled by coordinator",
        )

    def _make_worker_runtime_state(self, task: AgentTask, workspace: Path) -> dict:
        """Build a minimal shared state for the underlying AgentRuntime."""

        return {
            "run_id": f"worker-{uuid4().hex[:8]}",
            "_team_state": self._team_state,
            "task": task.objective,
            "workspace": workspace.resolve(strict=True),
            "history": [],
            "current_tool_call": None,
            "step_count": 0,
            "event_sequence": 0,
            "trace_events": [],
            "max_steps": task.max_steps,
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
            "verification_gate_enabled": self._enable_verification_gate,
        }

    def _on_runtime_event(
        self,
        event: str,
        payload: dict[str, Any],
        task_id: str,
        counters: WorkerRuntimeCounters,
    ) -> None:
        """Forward interesting runtime events into the team trace."""

        if event == "tool_call":
            counters.tool_call_count += 1
        elif event == "model_call":
            counters.model_call_count += 1

    def _derive_worker_status(self, final_state: dict) -> WorkerStatus:
        """Map AgentRuntime stop_reason to WorkerStatus.

        A stop_reason of "done" only means the model proposed completion. The
        Worker must also verify that no scoped tool call failed (scope/lease/CAS
        violation). If any required tool failed, the task cannot be COMPLETED.
        """

        stop_reason = final_state.get("stop_reason")
        if stop_reason == "cancelled":
            return WorkerStatus.CANCELLED
        if stop_reason in {"max_steps", "invalid_model_output"}:
            return WorkerStatus.FAILED
        if stop_reason in {"blocked_environment", "verification_failed", "reflection_limit", "repeated_failure"}:
            return WorkerStatus.BLOCKED

        # Even when the model says "done", hard tool failures recorded in history
        # override the proposal. Otherwise a model can paper over a scope denial.
        history = final_state.get("history", [])
        for entry in history:
            if entry.tool in {"file_write", "file_edit", "bash", "file_read", "grep"} and not entry.result.ok:
                error_code = entry.result.error_code or ""
                if error_code in {"scope_violation", "lease_conflict", "cas_conflict"}:
                    return WorkerStatus.FAILED

        if stop_reason in {"completed_verified", "done"}:
            return WorkerStatus.COMPLETED
        return WorkerStatus.COMPLETED if final_state.get("result") else WorkerStatus.FAILED

    def _extract_changed_files(self, final_state: dict) -> list[str]:
        """Collect paths touched by successful file_write/file_edit calls."""

        changed: set[str] = set()
        for entry in final_state.get("history", []):
            if entry.tool in {"file_write", "file_edit"} and entry.result.ok:
                path = entry.arguments.get("path")
                if isinstance(path, str):
                    changed.add(path)
        return sorted(changed)
