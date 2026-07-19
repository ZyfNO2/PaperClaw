"""Adapter that executes one durable task through the existing isolated Worker stack."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from time import sleep
from typing import Callable

from paperclaw.models.base import ChatModel
from paperclaw.multiagent.contracts import (
    AgentTask,
    TeamBudget,
    TeamStopReason,
    WorkerStatus,
)
from paperclaw.multiagent.semantic_coordinator import SemanticCoordinator

from .contracts import TaskExecutionResult, TaskRecord, TaskStatus


class SubagentTaskExecutor:
    """Run a durable task with fresh Worker context and scoped tools."""

    def __init__(
        self,
        model_factory: Callable[[str], ChatModel],
        *,
        judge_model_factory: Callable[[str], ChatModel] | None = None,
        enable_verification_gate: bool = True,
        event_handler: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._model_factory = model_factory
        self._judge_model_factory = judge_model_factory
        self._enable_verification_gate = enable_verification_gate
        self._event_handler = event_handler

    def __call__(
        self,
        task: TaskRecord,
        should_cancel: Callable[[], bool],
    ) -> TaskExecutionResult:
        metadata = dict(task.metadata)
        allowed_paths = _string_list(metadata.get("allowed_paths"), ["."])
        writable_paths = _string_list(metadata.get("writable_paths"), [])
        allowed_tools = _string_list(
            metadata.get("allowed_tools"),
            ["file_read", "grep"],
        )
        acceptance_criteria = _string_list(
            metadata.get("acceptance_criteria"),
            ["Return a concise structured result for the parent task."],
        )
        agent_task = AgentTask(
            task_id=task.task_id,
            title=str(metadata.get("title") or task.objective[:80]),
            objective=task.objective,
            acceptance_criteria=acceptance_criteria,
            allowed_paths=allowed_paths,
            writable_paths=writable_paths,
            allowed_tools=allowed_tools,
            dependencies=[],
            max_steps=task.max_steps,
            timeout_seconds=max(1, int(task.timeout_seconds)),
        )
        semantic_reserve = 2 if self._judge_model_factory is not None else 0
        budget = TeamBudget(
            max_agents=1,
            max_total_steps=task.max_steps,
            max_total_model_calls=max(task.max_steps + 2 + semantic_reserve, 4),
            max_wall_time_seconds=max(1, int(task.timeout_seconds)),
            max_fix_rounds=1,
        )
        coordinator = SemanticCoordinator(
            self._model_factory,
            Path(task.workspace),
            budget=budget,
            enable_verification_gate=self._enable_verification_gate,
            event_handler=self._project_event(task),
            judge_model_factory=self._judge_model_factory,
        )
        monitor_stop = Event()

        def monitor() -> None:
            while not monitor_stop.is_set():
                if should_cancel():
                    coordinator.cancel(task.task_id, [agent_task])
                    return
                sleep(0.05)

        monitor_thread = Thread(
            target=monitor,
            name=f"task-cancel-monitor:{task.task_id}",
            daemon=True,
        )
        monitor_thread.start()
        try:
            result = coordinator.run(task.objective, [agent_task])
        finally:
            monitor_stop.set()
            monitor_thread.join(timeout=1.0)

        worker = result.task_results.get(task.task_id)
        if worker is None:
            return TaskExecutionResult(
                TaskStatus.FAILED,
                error={"code": "missing_worker_result"},
                stop_reason="missing_worker_result",
            )
        output = {
            "summary": worker.summary,
            "changed_files": list(worker.changed_files),
            "unresolved_items": list(worker.unresolved_items),
            "review_findings": [finding.to_dict() for finding in result.review_findings],
            "team_summary": result.summary,
            "deterministic_verification": (
                worker.verification_result.to_dict()
                if worker.verification_result is not None
                else None
            ),
            "semantic_acceptance": (
                worker.semantic_judge_result.to_dict()
                if worker.semantic_judge_result is not None
                else None
            ),
        }
        common = {
            "output": output,
            "model_calls": worker.model_call_count,
            "tool_calls": worker.tool_call_count,
            "side_effect_state": "committed" if worker.changed_files else "none",
        }
        if worker.status is WorkerStatus.COMPLETED and result.stop_reason in {
            TeamStopReason.COMPLETED,
            TeamStopReason.ALL_TASKS_COMPLETED,
        }:
            return TaskExecutionResult(TaskStatus.SUCCEEDED, **common)
        if worker.status is WorkerStatus.CANCELLED or should_cancel():
            return TaskExecutionResult(
                TaskStatus.CANCELLED,
                stop_reason="cancel_requested",
                **common,
            )
        if worker.status is WorkerStatus.BLOCKED:
            semantic = worker.semantic_judge_result
            return TaskExecutionResult(
                TaskStatus.BLOCKED,
                error={
                    "code": (
                        "semantic_acceptance_"
                        + semantic.status
                        if semantic is not None
                        else "subagent_blocked"
                    ),
                    "reason_code": semantic.reason_code if semantic is not None else None,
                },
                stop_reason="semantic_acceptance_blocked"
                if semantic is not None
                else "subagent_blocked",
                **common,
            )
        return TaskExecutionResult(
            TaskStatus.FAILED,
            error={
                "code": "subagent_failed",
                "worker_status": worker.status.value,
                "team_stop_reason": result.stop_reason.value,
            },
            stop_reason="subagent_failed",
            **common,
        )

    def _project_event(self, task: TaskRecord):
        if self._event_handler is None:
            return None

        def emit(event_type: str, payload: dict) -> None:
            self._event_handler(
                event_type,
                {
                    "parent_run_id": task.parent_run_id,
                    "task_id": task.task_id,
                    "agent_id": payload.get("agent_id") or task.task_id,
                    **payload,
                },
            )

        return emit


def _string_list(value: object, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return result or list(default)


__all__ = ["SubagentTaskExecutor"]
