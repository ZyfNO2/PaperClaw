from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.planning import (
    AnswerUserQuestionTool,
    ApprovePlanTool,
    AskUserQuestionTool,
    EnterPlanModeTool,
    ExitPlanModeTool,
    PlanController,
    PlanPhase,
    SQLitePlanStore,
    compose_plan_registry,
)
from paperclaw.tools.base import ToolContext, ToolResult, ToolValidationError
from paperclaw.tools.registry import ToolRegistry


class WriteProbe:
    name = "file_write"
    description = "write probe"

    def __init__(self) -> None:
        self.calls = 0

    def validate(self, arguments):
        if "path" not in arguments:
            raise ToolValidationError("path required")

    def execute(self, arguments, context):
        self.calls += 1
        return ToolResult(True, "written")


def controller(tmp_path: Path) -> PlanController:
    return PlanController(SQLitePlanStore(tmp_path / "plans.sqlite3"), "scope-1")


def test_plan_mode_denies_mutation_until_explicit_approval(tmp_path: Path) -> None:
    control = controller(tmp_path)
    probe = WriteProbe()
    registry = compose_plan_registry(ToolRegistry([probe]), control)
    guarded = registry.get("file_write")
    context = ToolContext(tmp_path)

    assert EnterPlanModeTool(control).execute({}, context).ok
    assert control.phase is PlanPhase.PLANNING
    with pytest.raises(ToolValidationError, match="explicit approval"):
        guarded.validate({"path": "x"})

    artifact_result = ExitPlanModeTool(control).execute(
        {
            "title": "Implement feature",
            "summary": "Make a bounded change.",
            "steps": ["inspect", "edit", "test"],
            "risks": ["regression"],
            "verification": ["pytest"],
        },
        context,
    )
    artifact = json.loads(artifact_result.output)["plan"]
    assert artifact["status"] == "awaiting_approval"
    with pytest.raises(ToolValidationError, match="explicit approval"):
        guarded.validate({"path": "x"})

    approved = ApprovePlanTool(control).execute(
        {"plan_id": artifact["plan_id"], "approved": True},
        context,
    )
    assert json.loads(approved.output)["write_tools_allowed"] is True
    guarded.validate({"path": "x"})
    assert guarded.execute({"path": "x"}, context).ok
    assert probe.calls == 1


def test_rejected_plan_keeps_mutating_tools_denied(tmp_path: Path) -> None:
    control = controller(tmp_path)
    guarded = compose_plan_registry(ToolRegistry([WriteProbe()]), control).get(
        "file_write"
    )
    context = ToolContext(tmp_path)
    control.store.enter(control.scope_id)
    plan = control.store.create_artifact(
        control.scope_id,
        title="reject",
        summary="reject",
        steps=["one"],
        risks=[],
        verification=["test"],
    )
    control.store.decide(control.scope_id, plan.plan_id, approve=False)
    assert control.phase is PlanPhase.REJECTED
    with pytest.raises(ToolValidationError):
        guarded.validate({"path": "x"})


def test_ask_user_question_persists_without_inventing_an_answer(tmp_path: Path) -> None:
    control = controller(tmp_path)
    context = ToolContext(tmp_path)
    result = AskUserQuestionTool(control).execute(
        {
            "prompt": "Which migration strategy should be used?",
            "options": ["online", "offline"],
            "allow_free_text": False,
        },
        context,
    )

    assert result.ok is False
    assert result.error_code == "interaction_required"
    question = json.loads(result.output)["question"]
    assert question["status"] == "pending"
    assert question["answer"] is None

    answered = AnswerUserQuestionTool(control).execute(
        {"question_id": question["question_id"], "answer": "online"},
        context,
    )
    assert json.loads(answered.output)["question"]["answer"] == "online"
