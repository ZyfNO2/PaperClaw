"""Worker agent runtime.

A Worker runs exactly one AgentTask using a scoped view of the world: limited
tools, limited paths, and bounded steps. It wraps the existing v0.02 AgentRuntime
so Verify / Reflection remain available without modification.
"""

from __future__ import annotations

import json
import subprocess
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
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.events import emit_team_event
from paperclaw.multiagent.lease import LeaseManager
from paperclaw.multiagent.permissions import PermissionGuardLite
from paperclaw.multiagent.scoped_tools import WorkerRuntimeCounters, build_scoped_registry
from paperclaw.multiagent.semantic_judge import SemanticAcceptanceJudge


def _kill_process_tree(pid: int) -> None:
    """Terminate a process and its entire child tree.

    On Windows we use ``taskkill /T /F`` to kill the process tree. If that
    fails (e.g. the process already exited or taskkill is unavailable), we
    fall back to ``proc.kill()`` on the Popen object's PID. This is best-effort
    — the cancel event will still cause the AgentRuntime to stop between steps.
    """
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


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
        judge_model: ChatModel | None = None,
    ) -> None:
        self.agent_id = agent_id
        self._model = model
        self._judge_model = judge_model
        self._guard = guard
        self._lease_manager = lease_manager
        self._team_state = team_state
        self._enable_verification_gate = enable_verification_gate
        self._cancel_event = threading.Event()
        # Process registry: maps task_id -> list of running Popen objects.
        # Used by cancel() to kill long-running Bash subprocesses so the Worker
        # thread can exit promptly instead of waiting for communicate() to return.
        self._process_registry: dict[str, Any] = {
            "processes": {},
            "lock": threading.Lock(),
        }

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
        worker_task = _render_task_context(task)
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
                worker_task,
                workspace,
                max_steps=task.max_steps,
                event_handler=lambda event, payload: self._on_runtime_event(
                    event, payload, task.task_id, counters
                ),
                cancel_event=self._cancel_event,
                timeout_seconds=task.timeout_seconds,
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

        # Deterministic Verify is authoritative. A semantic judge may never
        # upgrade failed local evidence into a completed Worker result.
        if (
            self._enable_verification_gate
            and status == WorkerStatus.COMPLETED
            and verification_result is not None
            and verification_result.status != "passed"
        ):
            status = WorkerStatus.FAILED

        semantic_judge_result = None
        if status == WorkerStatus.COMPLETED and self._judge_model is not None:
            semantic_judge_result = SemanticAcceptanceJudge(self._judge_model).evaluate(
                task,
                worker_summary=final_state.get("result")
                or final_state.get("stop_reason")
                or "no result",
                deterministic_result=verification_result,
                changed_files=changed_files,
                unresolved_items=list(final_state.get("remaining_issues", [])),
            )
            # Judge calls are real Provider calls and must count against the same
            # team model-call budget as execution/reflection calls.
            counters.model_call_count += semantic_judge_result.attempt_count
            emit_team_event(
                self._team_state,
                "verification.semantic.completed",
                self.agent_id,
                task.task_id,
                status=semantic_judge_result.status,
                reason_code=semantic_judge_result.reason_code,
                attempt_count=semantic_judge_result.attempt_count,
                provider=semantic_judge_result.provider,
                model=semantic_judge_result.model,
                transient=semantic_judge_result.transient,
            )
            if semantic_judge_result.status == "rejected":
                status = WorkerStatus.FAILED
            elif semantic_judge_result.status != "passed":
                # Provider instability, protocol errors, and judge disagreement
                # are not equivalent to a deterministic business failure.
                status = WorkerStatus.BLOCKED

        emit_team_event(
            self._team_state,
            MessageType.TASK_COMPLETED.value
            if status == WorkerStatus.COMPLETED
            else MessageType.TASK_FAILED.value,
            self.agent_id,
            task.task_id,
            status=status.value if isinstance(status, WorkerStatus) else status,
            changed_files=changed_files,
            deterministic_verification=(
                verification_result.status if verification_result is not None else None
            ),
            semantic_acceptance=(
                semantic_judge_result.status if semantic_judge_result is not None else None
            ),
        )
        self._lease_manager.release_all_for_task(task.task_id)
        return WorkerResult(
            task_id=task.task_id,
            status=status,
            summary=final_state.get("result") or final_state.get("stop_reason") or "no result",
            changed_files=changed_files,
            verification_result=verification_result,
            semantic_judge_result=semantic_judge_result,
            unresolved_items=final_state.get("remaining_issues", []),
            handoff_notes=[f"steps={final_state.get('step_count', 0)}"],
            step_count=final_state.get("step_count", 0),
            model_call_count=counters.model_call_count,
            tool_call_count=counters.tool_call_count,
        )

    def cancel(self, task: AgentTask) -> WorkerResult:
        """Signal cancellation and terminate any running subprocesses.

        Leases are NOT released here — they are released by ``Worker.run()``
        when the runtime naturally exits after the cancel event is observed.
        Releasing leases before the Worker thread has stopped creates a window
        where a long-running Bash command can still write to files that another
        Worker has already acquired a lease for.

        If the Worker thread does not stop within the Coordinator's join timeout,
        ``_cancel_active_worker`` returns ``unknown_outcome`` and the leases
        remain held until the thread eventually finishes.
        """
        self._cancel_event.set()

        # Kill any registered subprocesses for this task so that long-running
        # Bash commands terminate immediately instead of running to completion.
        registry = self._process_registry
        with registry["lock"]:
            procs = registry["processes"].pop(task.task_id, [])
            for proc in procs:
                try:
                    if proc.poll() is None:
                        _kill_process_tree(proc.pid)
                except Exception:
                    pass  # best-effort; the cancel event will still stop the loop

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
            "_process_registry": self._process_registry,
            "_task_id": task.task_id,
            "task": _render_task_context(task),
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
        if stop_reason in {"max_steps", "invalid_model_output", "timeout"}:
            return WorkerStatus.FAILED
        if stop_reason in {
            "blocked_environment",
            "verification_failed",
            "reflection_limit",
            "repeated_failure",
        }:
            return WorkerStatus.BLOCKED

        # Even when the model says "done", hard tool failures recorded in history
        # override the proposal. Otherwise a model can paper over a scope denial.
        history = final_state.get("history", [])
        for entry in history:
            if entry.tool in {"file_write", "file_edit", "bash", "file_read", "grep"} and not entry.result.ok:
                error_code = entry.result.error_code or ""
                if error_code in {"scope_violation", "lease_conflict", "cas_conflict", "cas_missing"}:
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


def _render_task_context(task: AgentTask) -> str:
    """Render only the explicit task contract into a fresh worker context."""
    return json.dumps(
        {
            "task_id": task.task_id,
            "title": task.title,
            "objective": task.objective,
            "acceptance_criteria": task.acceptance_criteria,
            "allowed_paths": task.allowed_paths,
            "writable_paths": task.writable_paths,
            "allowed_tools": task.allowed_tools,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
