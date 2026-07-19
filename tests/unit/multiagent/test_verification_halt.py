from __future__ import annotations

import json
import threading

from paperclaw.agent.flow import AgentRuntime
from paperclaw.models.base import ModelTurn
from paperclaw.multiagent.contracts import AgentTask
from paperclaw.multiagent.worker import _render_task_context


class NoCallModel:
    def complete(self, prompt: str) -> ModelTurn:  # pragma: no cover - must not execute
        raise AssertionError("model must not be called after pre-start cancellation")


class InvalidOutputModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> ModelTurn:
        self.calls += 1
        return ModelTurn("not-json")


def test_verification_gate_pre_start_cancel_halts_without_done_proposal(tmp_path) -> None:
    cancel = threading.Event()
    cancel.set()
    runtime = AgentRuntime(NoCallModel(), enable_verification_gate=True)

    state = runtime.run(
        "inspect without starting",
        tmp_path,
        cancel_event=cancel,
        max_steps=3,
    )

    assert state["stop_reason"] == "cancelled"
    assert state["done_proposal"] is None
    assert state["verification_plan"] is None
    assert state["verification_result"] is None


def test_verification_gate_terminal_invalid_output_halts_without_verify(tmp_path) -> None:
    model = InvalidOutputModel()
    runtime = AgentRuntime(model, enable_verification_gate=True)

    state = runtime.run("return malformed output", tmp_path, max_steps=5)

    assert model.calls == 2
    assert state["stop_reason"] == "invalid_model_output"
    assert state["done_proposal"] is None
    assert state["verification_plan"] is None
    assert state["verification_result"] is None


def test_worker_task_context_requires_self_contained_evidence_backed_result() -> None:
    task = AgentTask(
        task_id="read-only",
        title="Inspect permissions",
        objective="Inspect permission boundaries and explain a denial path.",
        acceptance_criteria=["Cite inspected module paths", "Explain one denial path"],
        allowed_paths=["src/paperclaw/mcp"],
        writable_paths=[],
        allowed_tools=["file_read", "grep"],
    )

    rendered = json.loads(_render_task_context(task))
    contract = " ".join(rendered["completion_result_contract"])

    assert "self-contained evidence-backed deliverable" in contract
    assert "every acceptance criterion" in contract
    assert "exact inspected module paths" in contract
    assert rendered["acceptance_criteria"] == task.acceptance_criteria
