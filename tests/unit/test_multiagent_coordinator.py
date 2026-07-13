"""Integration tests for Coordinator / Worker / Reviewer."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from paperclaw.models.base import ModelTurn
from paperclaw.multiagent.contracts import AgentTask, TeamBudget, TeamStopReason
from paperclaw.multiagent.coordinator import Coordinator


class FakeModel:
    """Deterministic model that replays a scripted action sequence.

    An optional barrier can synchronize the first model call across multiple
    Workers so tests can deterministically trigger runtime races (e.g. lease
    conflicts on the same file).
    """

    def __init__(
        self,
        actions: list[dict | str],
        barrier: threading.Barrier | None = None,
    ) -> None:
        self.actions = iter(actions)
        self.prompts: list[str] = []
        self._barrier = barrier
        self._barrier_used = False

    def complete(self, prompt: str) -> ModelTurn:
        self.prompts.append(prompt)
        if self._barrier is not None and not self._barrier_used:
            self._barrier_used = True
            self._barrier.wait()
        value = next(self.actions)
        content = value if isinstance(value, str) else json.dumps(value)
        return ModelTurn(content=content)


def _action(name: str, arguments: dict, reason: str = "test") -> dict:
    return {"action": name, "arguments": arguments, "reason": reason}


def _done(result: str = "complete", verification: str = "verified by command") -> dict:
    return _action("done", {"result": result, "verification": verification, "remaining_issues": []})


def _factory_for(*action_sequences: list[dict | str]) -> callable:
    """Return a model factory that cycles through the given action sequences."""

    iterators = [iter(seq) for seq in action_sequences]

    def factory(agent_id: str) -> FakeModel:
        # Use the agent index to pick a sequence, defaulting to the last one.
        index = int(agent_id.split("-")[-1]) if "-" in agent_id else 0
        seq = action_sequences[min(index, len(action_sequences) - 1)]
        return FakeModel(seq)

    return factory


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def test_single_agent_path_for_simple_task(tmp_workspace: Path):
    """M-11: simple task stays single-agent."""

    task = AgentTask(
        task_id="t1",
        title="say hello",
        objective="say hello",
        acceptance_criteria=["produces hello"],
        allowed_paths=["."],
        allowed_tools=["bash"],
    )
    model = FakeModel([_done("hello")])
    coord = Coordinator(lambda _id: model, tmp_workspace, enable_verification_gate=False)
    result = coord.run("say hello", [task])
    assert result.stop_reason == TeamStopReason.COMPLETED
    assert result.task_results["t1"].status == "completed"


def test_two_independent_read_tasks(tmp_workspace: Path):
    """M-01: two independent read-only tasks complete in parallel."""

    tasks = [
        AgentTask(
            task_id="read_a",
            title="read a",
            objective="read a",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["file_read"],
        ),
        AgentTask(
            task_id="read_b",
            title="read b",
            objective="read b",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["file_read"],
        ),
    ]
    coord = Coordinator(
        _factory_for([_done("a done")], [_done("b done")]),
        tmp_workspace,
        enable_verification_gate=False,
    )
    result = coord.run("read two files", tasks)
    assert result.stop_reason == TeamStopReason.ALL_TASKS_COMPLETED
    assert result.task_results["read_a"].status == "completed"
    assert result.task_results["read_b"].status == "completed"


def test_two_independent_writes_no_conflict(tmp_workspace: Path):
    """M-02: two Workers write different files and merge successfully."""

    tasks = [
        AgentTask(
            task_id="write_a",
            title="write a",
            objective="write file a.py",
            acceptance_criteria=["a.py exists"],
            allowed_paths=["."],
            writable_paths=["src"],
            allowed_tools=["file_write", "bash"],
            expected_artifacts=["src/a.py"],
        ),
        AgentTask(
            task_id="write_b",
            title="write b",
            objective="write file b.py",
            acceptance_criteria=["b.py exists"],
            allowed_paths=["."],
            writable_paths=["src"],
            allowed_tools=["file_write", "bash"],
            expected_artifacts=["src/b.py"],
        ),
    ]
    seq_a = [
        _action("file_write", {"path": "src/a.py", "content": "a = 1\n"}),
        _action("bash", {"command": "python -m py_compile src/a.py"}),
        _done("wrote a.py"),
    ]
    seq_b = [
        _action("file_write", {"path": "src/b.py", "content": "b = 2\n"}),
        _action("bash", {"command": "python -m py_compile src/b.py"}),
        _done("wrote b.py"),
    ]
    coord = Coordinator(_factory_for(seq_a, seq_b), tmp_workspace, enable_verification_gate=False)
    result = coord.run("write two files", tasks)
    assert result.stop_reason == TeamStopReason.ALL_TASKS_COMPLETED
    assert (tmp_workspace / "src" / "a.py").exists()
    assert (tmp_workspace / "src" / "b.py").exists()


def test_write_same_file_rejected_by_dag(tmp_workspace: Path):
    """M-03: two tasks writing the same file are rejected at DAG validation."""

    tasks = [
        AgentTask(
            task_id="a",
            title="write shared",
            objective="write shared.py",
            acceptance_criteria=["shared.py exists"],
            allowed_paths=["."],
            writable_paths=["src/shared.py"],
            allowed_tools=["file_write"],
        ),
        AgentTask(
            task_id="b",
            title="write shared again",
            objective="write shared.py",
            acceptance_criteria=["shared.py exists"],
            allowed_paths=["."],
            writable_paths=["src/shared.py"],
            allowed_tools=["file_write"],
        ),
    ]
    coord = Coordinator(lambda _id: FakeModel([]), tmp_workspace)
    result = coord.run("write shared file", tasks)
    assert result.stop_reason == TeamStopReason.BLOCKED
    assert "conflict" in result.summary.lower()


def test_worker_scope_violation(tmp_workspace: Path):
    """M-05: Worker writing outside allowed scope is denied."""

    task = AgentTask(
        task_id="t1",
        title="write escape",
        objective="write outside scope",
        acceptance_criteria=["file written"],
        allowed_paths=["."],
        writable_paths=["src"],
        allowed_tools=["file_write"],
    )
    seq = [
        _action("file_write", {"path": "escape.py", "content": "x = 1\n"}),
        _done("done"),
    ]
    coord = Coordinator(_factory_for(seq), tmp_workspace, enable_verification_gate=False)
    result = coord.run("write escape", [task])
    assert result.task_results["t1"].status != "completed"


def test_dag_cycle_rejected(tmp_workspace: Path):
    """M-04: cyclic DAG is blocked."""

    tasks = [
        AgentTask(
            task_id="a",
            title="a",
            objective="a",
            acceptance_criteria=["done"],
            dependencies=["b"],
        ),
        AgentTask(
            task_id="b",
            title="b",
            objective="b",
            acceptance_criteria=["done"],
            dependencies=["a"],
        ),
    ]
    coord = Coordinator(lambda _id: FakeModel([]), tmp_workspace)
    result = coord.run("cycle", tasks)
    assert result.stop_reason == TeamStopReason.BLOCKED


def test_worker_inherits_verification_gate_from_coordinator(tmp_workspace: Path):
    """M-08: team mode must not bypass v0.02 Verify Gate by default."""

    coord = Coordinator(
        _factory_for([_done("ok")]),
        tmp_workspace,
        enable_verification_gate=True,
    )
    worker = coord._make_worker("worker-0")
    assert worker._enable_verification_gate is True

    coord_disabled = Coordinator(
        _factory_for([_done("ok")]),
        tmp_workspace,
        enable_verification_gate=False,
    )
    worker_disabled = coord_disabled._make_worker("worker-0")
    assert worker_disabled._enable_verification_gate is False


def test_runtime_lease_conflict_between_workers(tmp_workspace: Path):
    """D5: two parallel Workers contending the same file hit lease_conflict."""

    tasks = [
        AgentTask(
            task_id="slow",
            title="slow write",
            objective="write and hold",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            writable_paths=["src"],
            allowed_tools=["file_write", "bash"],
        ),
        AgentTask(
            task_id="fast",
            title="fast write",
            objective="write same file",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            writable_paths=["src"],
            allowed_tools=["file_write"],
        ),
    ]
    slow_seq = [
        _action("file_write", {"path": "src/collide.py", "content": "x = 1\n"}),
        _action("bash", {"command": "sleep 0.5"}),
        _done("slow done"),
    ]
    fast_seq = [
        _action("file_write", {"path": "src/collide.py", "content": "x = 2\n"}),
        _done("fast done"),
    ]

    # Synchronize the first model call so both Workers attempt file_write at
    # the same time, guaranteeing one of them hits a lease conflict.
    barrier = threading.Barrier(2, timeout=5)

    def factory(agent_id: str) -> FakeModel:
        seq = slow_seq if agent_id == "worker-0" else fast_seq
        return FakeModel(seq, barrier=barrier)

    coord = Coordinator(factory, tmp_workspace, enable_verification_gate=False)
    result = coord.run("contention", tasks)

    # One Worker must fail due to lease conflict; the other completes.
    statuses = {r.status for r in result.task_results.values()}
    assert "completed" in statuses
    assert "failed" in statuses or "blocked" in statuses

    # The lease-conflict event must be recorded in the team trace.
    event_types = {e["event_type"] for e in result.trace_events}
    assert "tool.lease_conflict" in event_types
