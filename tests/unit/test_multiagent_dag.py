"""Tests for Task DAG validation."""

from __future__ import annotations

import pytest

from paperclaw.multiagent.contracts import AgentTask
from paperclaw.multiagent.dag import compute_task_status, validate_task_dag


def _task(task_id: str, deps: list[str] | None = None, writable: list[str] | None = None) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        title=task_id,
        objective=f"do {task_id}",
        acceptance_criteria=["done"],
        dependencies=deps or [],
        writable_paths=writable or [],
    )


def test_valid_chain():
    tasks = [_task("a"), _task("b", deps=["a"])]
    result = validate_task_dag(tasks)
    assert result.valid
    assert result.topological_order == ["a", "b"]


def test_cycle_rejected():
    tasks = [_task("a", deps=["b"]), _task("b", deps=["a"])]
    result = validate_task_dag(tasks)
    assert not result.valid
    assert "cycle" in " ".join(result.errors).lower()


def test_missing_dependency_rejected():
    tasks = [_task("a", deps=["missing"])]
    result = validate_task_dag(tasks)
    assert not result.valid
    assert any("missing" in e for e in result.errors)


def test_write_conflict_rejected():
    tasks = [
        _task("a", writable=["src/shared.py"]),
        _task("b", writable=["src/shared.py"]),
    ]
    result = validate_task_dag(tasks)
    assert not result.valid
    assert any("conflict" in e for e in result.errors)


def test_write_conflict_allowed_when_ordered():
    tasks = [
        _task("a", writable=["src/shared.py"]),
        _task("b", deps=["a"], writable=["src/shared.py"]),
    ]
    result = validate_task_dag(tasks)
    assert result.valid


def test_no_acceptance_criteria_rejected():
    tasks = [AgentTask(task_id="a", title="a", objective="do a", acceptance_criteria=[])]
    result = validate_task_dag(tasks)
    assert not result.valid


def test_compute_task_status():
    tasks = [_task("a"), _task("b", deps=["a"]), _task("c", deps=["a"])]
    status = compute_task_status(tasks, {"a": None})
    assert status["a"].value == "completed"
    assert status["b"].value == "ready"
    assert status["c"].value == "ready"
