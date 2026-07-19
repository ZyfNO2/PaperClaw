"""Child-process entrypoint for one durable environment-backed Subagent task."""

from __future__ import annotations

from typing import Any, Mapping

from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.multiagent.judge_factory import build_judge_model_from_env

from .contracts import TaskExecutionResult, TaskRecord, TaskStatus
from .subagent import SubagentTaskExecutor


def run_env_subagent_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    raw_task = payload.get("task")
    if not isinstance(raw_task, Mapping):
        raise ValueError("task payload is required")
    task = _task_record_from_dict(raw_task)
    executor = SubagentTaskExecutor(
        lambda _agent_id: OpenAICompatibleModel.from_env(),
        judge_model_factory=lambda _agent_id: build_judge_model_from_env(),
    )
    result = executor(task, lambda: False)
    return _execution_result_to_dict(result)


def _task_record_from_dict(value: Mapping[str, Any]) -> TaskRecord:
    return TaskRecord(
        task_id=str(value.get("task_id") or ""),
        parent_run_id=_optional_string(value.get("parent_run_id")),
        objective=str(value.get("objective") or ""),
        workspace=str(value.get("workspace") or ""),
        status=TaskStatus(str(value.get("status") or TaskStatus.RUNNING.value)),
        version=int(value.get("version") or 0),
        attempt=int(value.get("attempt") or 0),
        max_attempts=int(value.get("max_attempts") or 1),
        max_steps=int(value.get("max_steps") or 1),
        timeout_seconds=float(value.get("timeout_seconds") or 1.0),
        cancel_requested=bool(value.get("cancel_requested", False)),
        lease_owner=_optional_string(value.get("lease_owner")),
        lease_expires_at=_optional_float(value.get("lease_expires_at")),
        last_heartbeat_at=_optional_float(value.get("last_heartbeat_at")),
        side_effect_state=str(value.get("side_effect_state") or "none"),
        created_at=float(value.get("created_at") or 0.0),
        updated_at=float(value.get("updated_at") or 0.0),
        started_at=_optional_float(value.get("started_at")),
        completed_at=_optional_float(value.get("completed_at")),
        stop_reason=_optional_string(value.get("stop_reason")),
        output=_mapping_or_none(value.get("output")),
        error=_mapping_or_none(value.get("error")),
        metadata=_mapping(value.get("metadata")),
        dependencies=tuple(
            item
            for item in value.get("dependencies", [])
            if isinstance(item, str) and item
        )
        if isinstance(value.get("dependencies"), list)
        else (),
    )


def _execution_result_to_dict(result: TaskExecutionResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "output": dict(result.output) if result.output is not None else None,
        "error": dict(result.error) if result.error is not None else None,
        "stop_reason": result.stop_reason,
        "side_effect_state": result.side_effect_state,
        "model_calls": result.model_calls,
        "tool_calls": result.tool_calls,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_or_none(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = ["run_env_subagent_payload"]
