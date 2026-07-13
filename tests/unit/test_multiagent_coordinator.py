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
    assert result.stop_reason == TeamStopReason.ALL_TASKS_COMPLETED
    assert result.task_results["t1"].status == "completed"


def test_single_agent_path_executes_dependent_chain(tmp_workspace: Path):
    """B1/B3/B5: sequential path must run every task in topological order."""

    tasks = [
        AgentTask(
            task_id="a",
            title="create a",
            objective="create a.py",
            acceptance_criteria=["a.py exists"],
            allowed_paths=["."],
            writable_paths=["src"],
            allowed_tools=["file_write"],
            expected_artifacts=["src/a.py"],
        ),
        AgentTask(
            task_id="b",
            title="read a",
            objective="read a.py",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["file_read"],
            dependencies=["a"],
        ),
    ]
    seq = [
        _action("file_write", {"path": "src/a.py", "content": "a = 1\n"}),
        _done("wrote a.py"),
        _action("file_read", {"path": "src/a.py"}),
        _done("read a.py"),
    ]
    coord = Coordinator(_factory_for(seq), tmp_workspace, enable_verification_gate=False)
    result = coord.run("dependent chain", tasks)
    assert result.stop_reason == TeamStopReason.ALL_TASKS_COMPLETED
    assert result.task_results["a"].status == "completed"
    assert result.task_results["b"].status == "completed"


def test_single_agent_path_blocks_downstream_on_failure(tmp_workspace: Path):
    """B5: failure in a sequential DAG blocks downstream tasks."""

    tasks = [
        AgentTask(
            task_id="a",
            title="fail",
            objective="fail",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
        ),
        AgentTask(
            task_id="b",
            title="never runs",
            objective="never runs",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
            dependencies=["a"],
        ),
    ]
    # Task a tries to write outside its writable scope and must fail.
    coord = Coordinator(
        _factory_for([
            _action("file_write", {"path": "escape.py", "content": "x = 1\n"}),
            _done("should not run"),
        ]),
        tmp_workspace,
        enable_verification_gate=False,
    )
    result = coord.run("failure blocks downstream", tasks)
    assert result.stop_reason == TeamStopReason.BLOCKED
    assert result.task_results["a"].status == "failed"
    assert result.task_results["b"].status == "blocked"


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


class SharedFakeModel:
    """Fake model that draws from a single shared iterator across Workers.

    Useful for fix-review tests where the original Worker and the Fix Task
    Worker must consume different scripted actions in order.
    """

    def __init__(self, shared_iterator: iter) -> None:
        self._iterator = shared_iterator
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> ModelTurn:
        self.prompts.append(prompt)
        value = next(self._iterator)
        content = value if isinstance(value, str) else json.dumps(value)
        return ModelTurn(content=content)


def test_parent_task_cancel_cascades_to_child(tmp_workspace: Path):
    """M-07: cancelling a parent task stops its dependent child tasks."""

    # Add an independent task so the Coordinator chooses the parallel path.
    tasks = [
        AgentTask(
            task_id="parent",
            title="parent",
            objective="sleep then finish",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
        ),
        AgentTask(
            task_id="child",
            title="child",
            objective="run after parent",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
            dependencies=["parent"],
        ),
        AgentTask(
            task_id="independent",
            title="independent",
            objective="finish quickly",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
        ),
    ]
    parent_seq = [
        _action("bash", {"command": "sleep 2"}),
        _done("parent done"),
    ]
    coord = Coordinator(
        _factory_for(parent_seq, [_done("child done")], [_done("independent done")]),
        tmp_workspace,
        enable_verification_gate=False,
    )

    result_container: dict[str, CoordinatorResult] = {}

    def run_coordinator() -> None:
        result_container["result"] = coord.run("cancel cascade", tasks)

    thread = threading.Thread(target=run_coordinator)
    thread.start()
    # Give the parent Worker time to start before cancelling it.
    thread.join(timeout=0.3)
    coord.cancel("parent", tasks)
    thread.join(timeout=10)

    result = result_container["result"]
    assert result.task_results["child"].status == "cancelled"
    assert result.stop_reason in {TeamStopReason.BLOCKED, TeamStopReason.CANCELLED}


def test_reviewer_blocker_creates_fix_task(tmp_workspace: Path):
    """M-09: a blocker/high Reviewer finding creates a Fix Task that can resolve it."""

    # Two independent tasks force the parallel path; one leaves a missing artifact.
    tasks = [
        AgentTask(
            task_id="good",
            title="good",
            objective="good",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
        ),
        AgentTask(
            task_id="incomplete",
            title="incomplete",
            objective="incomplete",
            acceptance_criteria=["artifact exists"],
            allowed_paths=["."],
            writable_paths=["src"],
            allowed_tools=["file_write"],
            expected_artifacts=["src/missing.py"],
        ),
    ]
    # Original Workers both say done; Fix Task Worker creates the missing file.
    shared = iter([
        _done("good done"),
        _done("incomplete done"),
        _action("file_write", {"path": "src/missing.py", "content": "x = 1\n"}),
        _done("fixed"),
    ])
    coord = Coordinator(
        lambda _id: SharedFakeModel(shared),
        tmp_workspace,
        enable_verification_gate=False,
        budget=TeamBudget(max_fix_rounds=2),
    )
    result = coord.run("fix missing artifact", tasks)

    # A fix task should have been created and completed.
    fix_tasks = [tid for tid in result.task_results if tid.startswith("fix-")]
    assert fix_tasks
    assert result.task_results[fix_tasks[0]].status == "completed"
    assert (tmp_workspace / "src" / "missing.py").exists()
    assert result.stop_reason == TeamStopReason.ALL_TASKS_COMPLETED


def test_reviewer_fix_round_limit(tmp_workspace: Path):
    """M-10: Reviewer stays unsatisfied until the fix-review round limit is hit."""

    tasks = [
        AgentTask(
            task_id="good",
            title="good",
            objective="good",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
        ),
        AgentTask(
            task_id="incomplete",
            title="incomplete",
            objective="incomplete",
            acceptance_criteria=["artifact exists"],
            allowed_paths=["."],
            writable_paths=["src"],
            allowed_tools=["file_write"],
            expected_artifacts=["src/missing.py"],
        ),
    ]
    # Original and every Fix Task just say done without creating the file.
    shared = iter([
        _done("good done"),
        _done("incomplete done"),
        _done("still no file"),
        _done("still no file"),
    ])
    coord = Coordinator(
        lambda _id: SharedFakeModel(shared),
        tmp_workspace,
        enable_verification_gate=False,
        budget=TeamBudget(max_fix_rounds=2),
    )
    result = coord.run("fix round limit", tasks)

    assert result.stop_reason == TeamStopReason.REFLECTION_LIMIT
    assert any(tid.startswith("fix-") for tid in result.task_results)


def test_team_step_budget_aggregated_across_workers(tmp_workspace: Path):
    """Team budget: total steps across Workers must respect max_total_steps."""

    tasks = [
        AgentTask(
            task_id="a",
            title="a",
            objective="a",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
            max_steps=10,
        ),
        AgentTask(
            task_id="b",
            title="b",
            objective="b",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
            max_steps=10,
        ),
    ]
    coord = Coordinator(
        _factory_for([_done("a done")], [_done("b done")]),
        tmp_workspace,
        enable_verification_gate=False,
        budget=TeamBudget(max_total_steps=1),
    )
    result = coord.run("budget test", tasks)

    # The team should stop because the step budget is exhausted or capped.
    total_steps = sum(r.step_count for r in result.task_results.values())
    assert total_steps <= coord.budget.max_total_steps
    assert result.summary.startswith("stop=budget_exhausted") or "steps=1/1" in result.summary


def test_plain_model_output_is_not_team_message(tmp_workspace: Path):
    """M-12: free-form model text does not automatically become an AgentMessage."""

    task = AgentTask(
        task_id="t1",
        title="say hello",
        objective="say hello",
        acceptance_criteria=["produces hello"],
        allowed_paths=["."],
        allowed_tools=["bash"],
    )
    coord = Coordinator(lambda _id: FakeModel([_done("hello")]), tmp_workspace, enable_verification_gate=False)
    result = coord.run("say hello", [task])

    # AgentMessage events are explicit runtime message channel events; model
    # output must not appear as a team message.
    message_events = [e for e in result.trace_events if "message" in e["event_type"]]
    assert not message_events
    assert result.stop_reason == TeamStopReason.ALL_TASKS_COMPLETED


def test_team_model_call_budget_reservation_blocks_parallel_overshoot(tmp_workspace: Path):
    """P0 #3: parallel Workers cannot collectively exceed max_total_model_calls.

    Two independent tasks each with max_steps=2 are scheduled in parallel.
    With max_total_model_calls=1, the reservation mechanism must prevent the
    second task from starting — the projected model calls would exceed the limit.
    """

    tasks = [
        AgentTask(
            task_id="a",
            title="a",
            objective="a",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
            max_steps=2,
        ),
        AgentTask(
            task_id="b",
            title="b",
            objective="b",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
            max_steps=2,
        ),
    ]
    coord = Coordinator(
        _factory_for([_done("a done")], [_done("b done")]),
        tmp_workspace,
        enable_verification_gate=False,
        budget=TeamBudget(max_total_model_calls=1, max_total_steps=100),
    )
    result = coord.run("model-call budget", tasks)

    total_model_calls = sum(r.model_call_count for r in result.task_results.values())
    assert total_model_calls <= coord.budget.max_total_model_calls
    # At most one task should have run; the other must be cancelled.
    statuses = {r.status for r in result.task_results.values()}
    assert "cancelled" in statuses or "blocked" in statuses or result.stop_reason == TeamStopReason.BLOCKED


def test_task_timeout_enforced(tmp_workspace: Path):
    """P0 #4: AgentTask.timeout_seconds causes the runtime to stop on timeout."""

    task = AgentTask(
        task_id="t1",
        title="slow task",
        objective="do something slow",
        acceptance_criteria=["done"],
        allowed_paths=["."],
        allowed_tools=["bash"],
        max_steps=20,
        timeout_seconds=1,
    )
    # The model will keep proposing bash sleep actions that exceed the timeout.
    slow_seq = [
        _action("bash", {"command": "sleep 2"}),
        _done("done"),
    ]
    coord = Coordinator(_factory_for(slow_seq), tmp_workspace, enable_verification_gate=False)
    result = coord.run("timeout test", [task])

    # The task should fail due to timeout, not complete normally.
    assert result.task_results["t1"].status == "failed"


def test_absolute_wall_time_deadline_shared_across_rounds(tmp_workspace: Path):
    """P0 #4: fix-review rounds must not reset the wall-time deadline.

    Uses a very short wall-time budget so that even if fix rounds try to start,
    the absolute deadline is already exceeded and the team stops with
    BUDGET_EXHAUSTED rather than running indefinitely.
    """

    tasks = [
        AgentTask(
            task_id="a",
            title="a",
            objective="a",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
            max_steps=5,
        ),
        AgentTask(
            task_id="b",
            title="b",
            objective="b",
            acceptance_criteria=["done"],
            allowed_paths=["."],
            allowed_tools=["bash"],
            max_steps=5,
        ),
    ]
    # Each Worker sleeps via bash so wall time elapses.
    slow_seq = [
        _action("bash", {"command": "sleep 1"}),
        _done("done"),
    ]
    coord = Coordinator(
        _factory_for(slow_seq, slow_seq),
        tmp_workspace,
        enable_verification_gate=False,
        budget=TeamBudget(max_wall_time_seconds=0, max_total_steps=100),
    )
    result = coord.run("wall-time deadline", tasks)

    assert result.stop_reason == TeamStopReason.BUDGET_EXHAUSTED


def test_cancel_does_not_release_lease_immediately(tmp_workspace: Path):
    """P0 #5: Worker.cancel() must not release leases before the thread stops.

    Releasing leases early creates a window where a long-running Bash command
    can still write to files that another Worker has already acquired a lease
    for. Leases should only be released by Worker.run() after the runtime
    has naturally exited.

    Regression guard: if someone adds ``release_all_for_task`` back to
    ``Worker.cancel()``, the post-cancel lease assertion below will fail.
    """

    import time as _time

    from paperclaw.multiagent.lease import LeaseManager
    from paperclaw.multiagent.permissions import PermissionGuardLite
    from paperclaw.multiagent.worker import Worker

    task = AgentTask(
        task_id="cancel-test",
        title="write then slow bash",
        objective="write a file then run a slow bash command",
        acceptance_criteria=["done"],
        allowed_paths=["."],
        writable_paths=["src"],
        allowed_tools=["file_write", "bash"],
    )
    lease_mgr = LeaseManager(tmp_workspace)
    guard = PermissionGuardLite(tmp_workspace)
    team_state = {"run_id": "test", "event_sequence": 0, "trace_events": []}

    model = FakeModel([
        _action("file_write", {"path": "src/cancel_test.py", "content": "x = 1\n"}),
        _action("bash", {"command": "sleep 5"}),
        _done("done"),
    ])
    worker = Worker("w-cancel", model, guard, lease_mgr, team_state, enable_verification_gate=False)

    result_holder: dict = {}

    def run_worker():
        result_holder["result"] = worker.run(task, tmp_workspace)

    t = threading.Thread(target=run_worker)
    t.start()

    # Poll until the Worker has acquired the lease for src/cancel_test.py.
    # This guarantees cancel() is called only after a lease exists to protect,
    # so the post-cancel assertion is meaningful rather than vacuously true.
    poll_deadline = _time.monotonic() + 3.0
    while _time.monotonic() < poll_deadline:
        if lease_mgr.owner("src/cancel_test.py") is not None:
            break
        _time.sleep(0.02)
    else:
        pytest.fail("Worker did not acquire lease for src/cancel_test.py within 3s")

    # Snapshot the lease holder before cancel so we can verify it survives.
    lease_before = lease_mgr.owner("src/cancel_test.py")
    assert lease_before is not None
    assert lease_before.task_id == "cancel-test"

    # Cancel the worker. cancel() must NOT release the lease — only Worker.run()
    # releases it when the thread naturally exits.
    cancel_result = worker.cancel(task)
    assert cancel_result.status == "cancelled"

    # Core invariant: immediately after cancel(), the lease must still be held
    # by the task. If cancel() released it here, another Worker could acquire
    # the lease while the cancelled Worker's bash subprocess is still writing,
    # producing a write-after-free race.
    lease_after_cancel = lease_mgr.owner("src/cancel_test.py")
    assert lease_after_cancel is not None, (
        "cancel() released the lease before the Worker thread stopped — "
        "this creates a write-after-free window for parallel Workers"
    )
    assert lease_after_cancel.task_id == "cancel-test"

    # Wait for the Worker thread to finish (bash process should be killed by
    # _kill_process_tree in cancel()).
    t.join(timeout=10)
    assert not t.is_alive(), "Worker thread should have terminated after cancel"

    # After the Worker thread naturally exits, Worker.run() releases the lease.
    assert lease_mgr.owner("src/cancel_test.py") is None, (
        "lease was not released after Worker thread terminated"
    )

    result = result_holder.get("result")
    assert result is not None
    assert result.status != "completed"
