"""Main-agent tool for bounded, isolated subagent task delegation."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from time import sleep
from typing import Any, Callable, Mapping

from paperclaw.models.base import ChatModel
from paperclaw.tools.base import (
    ToolContext,
    ToolResult,
    ToolValidationError,
    require_string,
    truncate,
)

from .budget_accounting import install_subagent_budget_accounting
from .contracts import AgentTask, TeamBudget, TeamStopReason, WorkerStatus
from .coordinator import Coordinator, CoordinatorResult

_ALLOWED_WORKER_TOOLS = frozenset(
    {"file_read", "file_write", "file_edit", "grep", "bash"}
)
_MAX_TASKS = 4
_MAX_AGENTS = 3
_MAX_TASK_STEPS = 30
_MAX_TASK_TIMEOUT_SECONDS = 300


class SubagentTaskTool:
    """Delegate a bounded task DAG to fresh Workers and return summaries only."""

    name = "delegate_tasks"
    description = (
        "Delegate 1-4 self-contained coding/research tasks to isolated subagents. "
        "Independent tasks may run in parallel. Arguments: "
        '{"goal":"overall goal","max_agents":2,"tasks":[{"task_id":"t1",'
        '"title":"short title","objective":"complete instruction",'
        '"acceptance_criteria":["measurable result"],"allowed_paths":["src"],'
        '"writable_paths":[],"allowed_tools":["file_read","grep"],'
        '"dependencies":[],"max_steps":8,"timeout_seconds":120}]}. '
        "Workers start with fresh context, cannot delegate recursively, and return "
        "only structured summaries. Child usage counts against parent run budgets."
    )

    def __init__(
        self,
        model_factory: Callable[[str], ChatModel],
        *,
        coordinator_factory: Callable[..., Coordinator] = Coordinator,
        enable_verification_gate: bool = True,
        event_handler: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        install_subagent_budget_accounting()
        self._model_factory = model_factory
        self._coordinator_factory = coordinator_factory
        self._enable_verification_gate = enable_verification_gate
        self._event_handler = event_handler

    def validate(self, arguments: dict[str, Any]) -> None:
        _parse_request(arguments, None, None)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        goal, tasks, budget = _parse_request(
            arguments,
            context.remaining_model_calls,
            context.remaining_tool_calls,
        )
        if context.remaining_model_calls == 0:
            return ToolResult(
                False,
                "parent model-call budget has no capacity for subagents",
                "parent_budget_exhausted",
                _usage_metadata(tasks, budget, None),
            )
        stop_token = context.stop_token
        if stop_token is not None and stop_token.is_cancelled:
            return ToolResult(
                False,
                "subagent delegation cancelled",
                "cancelled",
                _usage_metadata(tasks, budget, None),
            )

        coordinator = self._coordinator_factory(
            self._model_factory,
            Path(context.workspace),
            budget=budget,
            enable_verification_gate=self._enable_verification_gate,
            event_handler=self._event_handler,
        )
        holder: dict[str, Any] = {}

        def run_team() -> None:
            try:
                holder["result"] = coordinator.run(goal, tasks)
            except Exception as exc:
                holder["error"] = exc

        worker = Thread(target=run_team, name="paperclaw-subagent-team", daemon=True)
        worker.start()
        while worker.is_alive():
            if stop_token is not None and stop_token.is_cancelled:
                for task in tasks:
                    coordinator.cancel(task.task_id, tasks)
                worker.join(timeout=15)
                if worker.is_alive():
                    return ToolResult(
                        False,
                        "subagent cancellation outcome is unknown",
                        "unknown_outcome",
                        _usage_metadata(tasks, budget, None),
                    )
                result = holder.get("result")
                return ToolResult(
                    False,
                    "subagent delegation cancelled",
                    "cancelled",
                    _usage_metadata(
                        tasks,
                        budget,
                        result if isinstance(result, CoordinatorResult) else None,
                    ),
                )
            worker.join(timeout=0.05)
            if worker.is_alive():
                sleep(0.01)

        error = holder.get("error")
        if error is not None:
            return ToolResult(
                False,
                f"subagent coordinator failed: {type(error).__name__}: {error}",
                "subagent_runtime_error",
                _usage_metadata(tasks, budget, None),
            )
        result = holder.get("result")
        if not isinstance(result, CoordinatorResult):
            return ToolResult(
                False,
                "subagent coordinator returned no structured result",
                "subagent_runtime_error",
                _usage_metadata(tasks, budget, None),
            )

        payload = _result_payload(result)
        rendered, was_truncated = truncate(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            context.output_limit,
        )
        succeeded = result.stop_reason in {
            TeamStopReason.COMPLETED,
            TeamStopReason.ALL_TASKS_COMPLETED,
        }
        metadata = _usage_metadata(tasks, budget, result)
        metadata["result_truncated"] = was_truncated
        return ToolResult(
            succeeded,
            rendered,
            None if succeeded else "subagent_tasks_incomplete",
            metadata,
        )


def _parse_request(
    arguments: Mapping[str, Any],
    remaining_model_calls: int | None,
    remaining_tool_calls: int | None,
) -> tuple[str, list[AgentTask], TeamBudget]:
    if not isinstance(arguments, Mapping):
        raise ToolValidationError("arguments must be an object")
    goal = require_string(dict(arguments), "goal")
    raw_tasks = arguments.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ToolValidationError("tasks must be a non-empty list")
    if len(raw_tasks) > _MAX_TASKS:
        raise ToolValidationError(f"tasks must contain at most {_MAX_TASKS} items")

    tasks = [_parse_task(index, value) for index, value in enumerate(raw_tasks)]
    task_ids = [task.task_id for task in tasks]
    if len(set(task_ids)) != len(task_ids):
        raise ToolValidationError("task_id values must be unique")
    known_ids = set(task_ids)
    for task in tasks:
        unknown = sorted(set(task.dependencies) - known_ids)
        if unknown:
            raise ToolValidationError(
                f"task {task.task_id} has unknown dependencies: {', '.join(unknown)}"
            )

    max_agents = _bounded_int(
        arguments.get("max_agents", 2),
        "max_agents",
        1,
        _MAX_AGENTS,
    )
    requested_steps = min(100, sum(task.max_steps for task in tasks))
    # v0.22 reserves up to two Reflection calls and two semantic-judge calls
    # per task. Legacy callers simply receive extra headroom; actual usage is
    # still measured and charged through WorkerResult counters.
    requested_models = min(120, requested_steps + (4 * len(tasks)))
    parent_model_cap = (
        requested_models
        if remaining_model_calls is None
        else max(1, min(requested_models, remaining_model_calls))
    )
    parent_tool_cap = (
        requested_steps
        if remaining_tool_calls is None
        else max(0, remaining_tool_calls)
    )
    max_steps = max(
        1,
        min(requested_steps, parent_model_cap + parent_tool_cap),
    )
    max_timeout = max(task.timeout_seconds for task in tasks)
    budget = TeamBudget(
        max_agents=min(max_agents, len(tasks)),
        max_total_steps=max_steps,
        max_total_model_calls=parent_model_cap,
        max_wall_time_seconds=min(_MAX_TASK_TIMEOUT_SECONDS, max_timeout),
        max_fix_rounds=1,
    )
    return goal, tasks, budget


def _parse_task(index: int, value: Any) -> AgentTask:
    if not isinstance(value, Mapping):
        raise ToolValidationError(f"tasks[{index}] must be an object")
    item = dict(value)
    task_id = require_string(item, "task_id")
    title = require_string(item, "title")
    objective = require_string(item, "objective")
    criteria = _string_list(
        item.get("acceptance_criteria"),
        "acceptance_criteria",
        required=True,
    )
    allowed_paths = _string_list(
        item.get("allowed_paths", ["."]),
        "allowed_paths",
    )
    writable_paths = _string_list(
        item.get("writable_paths", []),
        "writable_paths",
    )
    allowed_tools = _string_list(
        item.get("allowed_tools", ["file_read", "grep"]),
        "allowed_tools",
    )
    unknown_tools = sorted(set(allowed_tools) - _ALLOWED_WORKER_TOOLS)
    if unknown_tools:
        raise ToolValidationError(
            "subagents cannot use unknown or recursive tools: "
            + ", ".join(unknown_tools)
        )
    dependencies = _string_list(item.get("dependencies", []), "dependencies")
    max_steps = _bounded_int(
        item.get("max_steps", 8),
        "max_steps",
        1,
        _MAX_TASK_STEPS,
    )
    timeout_seconds = _bounded_int(
        item.get("timeout_seconds", 120),
        "timeout_seconds",
        1,
        _MAX_TASK_TIMEOUT_SECONDS,
    )
    return AgentTask(
        task_id=task_id,
        title=title,
        objective=objective,
        acceptance_criteria=criteria,
        allowed_paths=allowed_paths,
        writable_paths=writable_paths,
        allowed_tools=allowed_tools,
        dependencies=dependencies,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
    )


def _string_list(value: Any, name: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ToolValidationError(f"{name} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ToolValidationError(f"{name} must contain non-empty strings")
        result.append(item.strip())
    if required and not result:
        raise ToolValidationError(f"{name} must not be empty")
    return result


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolValidationError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ToolValidationError(f"{name} must be within [{minimum}, {maximum}]")
    return value


def _usage_totals(result: CoordinatorResult | None) -> tuple[int, int, int]:
    if result is None:
        return 0, 0, 0
    steps = sum(item.step_count for item in result.task_results.values())
    model_calls = sum(item.model_call_count for item in result.task_results.values())
    tool_calls = sum(item.tool_call_count for item in result.task_results.values())
    return steps, model_calls, tool_calls


def _usage_metadata(
    tasks: list[AgentTask],
    budget: TeamBudget,
    result: CoordinatorResult | None,
) -> dict[str, Any]:
    steps, model_calls, tool_calls = _usage_totals(result)
    return {
        "task_count": len(tasks),
        "max_agents": budget.max_agents,
        "context_isolation": "fresh_worker_state",
        "recursive_delegation": False,
        "child_steps": steps,
        "child_model_calls": model_calls,
        "child_tool_calls": tool_calls,
        "team_model_call_limit": budget.max_total_model_calls,
        "team_step_limit": budget.max_total_steps,
    }


def _result_payload(result: CoordinatorResult) -> dict[str, Any]:
    stop_reason = (
        result.stop_reason.value
        if isinstance(result.stop_reason, TeamStopReason)
        else str(result.stop_reason)
    )
    tasks: dict[str, Any] = {}
    for task_id, worker_result in sorted(result.task_results.items()):
        status = (
            worker_result.status.value
            if isinstance(worker_result.status, WorkerStatus)
            else str(worker_result.status)
        )
        tasks[task_id] = {
            "status": status,
            "summary": worker_result.summary,
            "changed_files": list(worker_result.changed_files),
            "unresolved_items": list(worker_result.unresolved_items),
            "steps": worker_result.step_count,
            "model_calls": worker_result.model_call_count,
            "tool_calls": worker_result.tool_call_count,
            "deterministic_verification": (
                worker_result.verification_result.to_dict()
                if worker_result.verification_result is not None
                else None
            ),
            "semantic_acceptance": (
                worker_result.semantic_judge_result.to_dict()
                if worker_result.semantic_judge_result is not None
                else None
            ),
        }
    return {
        "stop_reason": stop_reason,
        "summary": result.summary,
        "tasks": tasks,
        "review_findings": [finding.to_dict() for finding in result.review_findings],
    }


__all__ = ["SubagentTaskTool"]
