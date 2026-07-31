"""Strict JSON/JSONL loading for evaluation cases."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    CaseExpectation, CaseLimits, EVALUATION_SCHEMA_VERSION, EvaluationCase,
    GateExpectation, VALID_MODES, VALID_ROLES, VALID_TERMINAL_STATES,
)

_TOP = {"schema_version", "case_id", "category", "mode", "request", "plan", "expectation", "limits", "metadata"}
_EXPECT = {"terminal_states", "required_roles", "required_tools", "allowed_tools", "forbidden_tools", "required_output_fields", "expected_gate"}
_LIMITS = {"max_steps", "max_tool_calls", "max_retries", "timeout_seconds", "loop_window"}


class CaseValidationError(ValueError):
    pass


def load_cases(path: str | Path) -> tuple[EvaluationCase, ...]:
    source = Path(path)
    rows: list[Any]
    if source.suffix.lower() == ".jsonl":
        rows = []
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise CaseValidationError(f"invalid JSON on line {number}") from exc
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else [payload]
    cases = tuple(_resolve_plan_source(parse_case(row), source.parent) for row in rows)
    identifiers = [case.case_id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise CaseValidationError("case_id values must be unique")
    return cases


def _resolve_plan_source(case: EvaluationCase, dataset_dir: Path) -> EvaluationCase:
    if not case.plan or "source" not in case.plan:
        return case
    declared = Path(str(case.plan["source"]))
    if declared.is_absolute():
        raise CaseValidationError("plan.source must be relative to the dataset directory")
    root = dataset_dir.resolve()
    plan_path = (root / declared).resolve()
    if not plan_path.is_relative_to(root):
        raise CaseValidationError("plan.source must remain inside the dataset directory")
    if not plan_path.is_file():
        raise CaseValidationError(f"plan.source does not exist: {declared}")
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    parsed = _parse_plan({"tasks": _object(payload, "plan source").get("tasks")})
    assert parsed is not None
    return replace(case, plan={"source": str(declared), "tasks": parsed["tasks"]})


def parse_case(payload: Any) -> EvaluationCase:
    row = _object(payload, "case")
    _reject_unknown(row, _TOP, "case")
    if str(row.get("schema_version")) != EVALUATION_SCHEMA_VERSION:
        raise CaseValidationError("unsupported schema_version")
    case_id = _text(row.get("case_id"), "case_id")
    category = _text(row.get("category"), "category")
    mode = _text(row.get("mode", "offline"), "mode")
    if mode not in VALID_MODES:
        raise CaseValidationError(f"unknown mode: {mode}")
    request = _object(row.get("request"), "request")
    _reject_unknown(request, {"request_id", "input"}, "request")
    _text(request.get("request_id"), "request.request_id")
    _text(request.get("input"), "request.input")
    raw_expect = _object(row.get("expectation"), "expectation")
    _reject_unknown(raw_expect, _EXPECT, "expectation")
    terminal_states = _strings(raw_expect.get("terminal_states"), "terminal_states", required=True)
    unknown_states = set(terminal_states) - VALID_TERMINAL_STATES
    if unknown_states:
        raise CaseValidationError(f"unknown terminal state(s): {sorted(unknown_states)}")
    roles = _strings(raw_expect.get("required_roles", ()), "required_roles")
    if set(roles) - VALID_ROLES:
        raise CaseValidationError("required_roles contains an unknown role")
    raw_gate = raw_expect.get("expected_gate")
    gate = None
    if raw_gate is not None:
        gate_row = _object(raw_gate, "expected_gate")
        _reject_unknown(gate_row, {"required", "action_type", "reason_code"}, "expected_gate")
        if not isinstance(gate_row.get("required"), bool):
            raise CaseValidationError("expected_gate.required must be boolean")
        gate = GateExpectation(
            gate_row["required"],
            _optional_text(gate_row.get("action_type")),
            _optional_text(gate_row.get("reason_code")),
        )
    raw_limits = _object(row.get("limits", {}), "limits")
    _reject_unknown(raw_limits, _LIMITS, "limits")
    limits = CaseLimits(**{key: _positive_int(value, f"limits.{key}") for key, value in raw_limits.items()})
    expectation = CaseExpectation(
        terminal_states=terminal_states,
        required_roles=roles,
        required_tools=_strings(raw_expect.get("required_tools", ()), "required_tools"),
        allowed_tools=_strings(raw_expect.get("allowed_tools", ()), "allowed_tools"),
        forbidden_tools=_strings(raw_expect.get("forbidden_tools", ()), "forbidden_tools"),
        required_output_fields=_strings(raw_expect.get("required_output_fields", ()), "required_output_fields"),
        expected_gate=gate,
    )
    plan = _parse_plan(row.get("plan"))
    required_tools = set(expectation.required_tools)
    allowed_tools = set(expectation.allowed_tools)
    forbidden_tools = set(expectation.forbidden_tools)
    if required_tools & forbidden_tools:
        raise CaseValidationError("required_tools and forbidden_tools must not overlap")
    if allowed_tools and not required_tools <= allowed_tools:
        raise CaseValidationError("required_tools must be included in allowed_tools")
    if allowed_tools & forbidden_tools:
        raise CaseValidationError("allowed_tools and forbidden_tools must not overlap")
    return EvaluationCase(case_id, category, mode, dict(request), expectation, limits, plan, dict(_object(row.get("metadata", {}), "metadata")))


def _parse_plan(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    plan = _object(value, "plan")
    _reject_unknown(plan, {"source", "tasks"}, "plan")
    source = plan.get("source")
    tasks = plan.get("tasks")
    if (source is None) == (tasks is None):
        raise CaseValidationError("plan must contain exactly one of source or tasks")
    if source is not None:
        return {"source": _text(source, "plan.source")}
    if not isinstance(tasks, list) or not tasks:
        raise CaseValidationError("plan.tasks must be a non-empty array")
    normalized = []
    for index, task in enumerate(tasks):
        item = _object(task, f"plan.tasks[{index}]")
        _reject_unknown(item, {"task_id"}, f"plan.tasks[{index}]")
        normalized.append({"task_id": _text(item.get("task_id"), f"plan.tasks[{index}].task_id")})
    ids = [item["task_id"] for item in normalized]
    if len(set(ids)) != len(ids):
        raise CaseValidationError("plan task_id values must be unique")
    return {"tasks": normalized}


def _reject_unknown(row: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(row) - allowed)
    if unknown:
        raise CaseValidationError(f"unknown {label} field(s): {unknown}")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CaseValidationError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CaseValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _strings(value: Any, label: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) and not isinstance(value, tuple):
        raise CaseValidationError(f"{label} must be an array")
    result = tuple(_text(item, label) for item in value)
    if required and not result:
        raise CaseValidationError(f"{label} must not be empty")
    if len(set(result)) != len(result):
        raise CaseValidationError(f"{label} must contain unique values")
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CaseValidationError(f"{label} must be a positive integer")
    return value


__all__ = ["CaseValidationError", "load_cases", "parse_case"]
