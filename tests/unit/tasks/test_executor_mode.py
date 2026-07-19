from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from paperclaw.tasks.bootstrap import _normalize_executor_mode, get_or_create_task_runtime
from paperclaw.tasks.process_executor import SubprocessSubagentTaskExecutor
from paperclaw.tasks.subagent import SubagentTaskExecutor


def test_executor_mode_normalization() -> None:
    assert _normalize_executor_mode("inprocess") == "inprocess"
    assert _normalize_executor_mode("THREAD") == "inprocess"
    assert _normalize_executor_mode("process") == "subprocess"
    assert _normalize_executor_mode(" subprocess ") == "subprocess"
    with pytest.raises(ValueError, match="inprocess or subprocess"):
        _normalize_executor_mode("remote")


def test_task_runtime_can_opt_into_subprocess_without_constructing_parent_models(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def model_factory(agent_id: str):
        calls.append(agent_id)
        raise AssertionError("subprocess composition must not construct parent models")

    runtime = get_or_create_task_runtime(
        model_factory,
        cache_key=f"subprocess-{uuid4().hex}",
        database=tmp_path / "tasks.sqlite3",
        worker_id="test-subprocess-worker",
        executor_mode="subprocess",
    )
    try:
        assert isinstance(runtime.supervisor._executor, SubprocessSubagentTaskExecutor)
        assert calls == []
    finally:
        runtime.supervisor.stop()


def test_task_runtime_default_remains_inprocess(tmp_path: Path) -> None:
    runtime = get_or_create_task_runtime(
        lambda _agent_id: None,  # type: ignore[return-value]
        cache_key=f"inprocess-{uuid4().hex}",
        database=tmp_path / "tasks.sqlite3",
        worker_id="test-inprocess-worker",
    )
    try:
        assert isinstance(runtime.supervisor._executor, SubagentTaskExecutor)
    finally:
        runtime.supervisor.stop()
