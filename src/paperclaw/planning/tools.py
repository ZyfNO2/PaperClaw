"""Plan Mode tools and permission guard composition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from paperclaw.tools.base import (
    ToolContext,
    ToolResult,
    ToolValidationError,
    require_string,
    truncate,
)
from paperclaw.tools.registry import ToolRegistry

from .runtime import PlanPhase, SQLitePlanStore

_MUTATING_TOOLS = frozenset({"file_write", "file_edit", "bash"})


class PlanController:
    def __init__(self, store: SQLitePlanStore, scope_id: str) -> None:
        self.store = store
        self.scope_id = scope_id

    @property
    def phase(self) -> PlanPhase:
        return self.store.phase(self.scope_id)


class EnterPlanModeTool:
    name = "enter_plan_mode"
    description = (
        "Enter read-only Plan Mode. While active, file writes, edits and Bash are "
        "denied until a structured plan is approved. No arguments."
    )

    def __init__(self, controller: PlanController) -> None:
        self.controller = controller

    def validate(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ToolValidationError("enter_plan_mode accepts no arguments")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        phase = self.controller.store.enter(self.controller.scope_id)
        return _result({"phase": phase.value, "write_tools_allowed": False}, context)


class ExitPlanModeTool:
    name = "exit_plan_mode"
    description = (
        "Submit a structured Plan Artifact and wait for user approval. Arguments: "
        "title, summary, steps, risks, verification. This does not execute the plan."
    )

    def __init__(self, controller: PlanController) -> None:
        self.controller = controller

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "title")
        require_string(arguments, "summary")
        _string_list(arguments.get("steps"), "steps", required=True)
        _string_list(arguments.get("risks", []), "risks")
        _string_list(arguments.get("verification"), "verification", required=True)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        artifact = self.controller.store.create_artifact(
            self.controller.scope_id,
            title=require_string(arguments, "title"),
            summary=require_string(arguments, "summary"),
            steps=_string_list(arguments.get("steps"), "steps", required=True),
            risks=_string_list(arguments.get("risks", []), "risks"),
            verification=_string_list(
                arguments.get("verification"),
                "verification",
                required=True,
            ),
        )
        return _result(
            {
                "plan": artifact.to_dict(),
                "approval_required": True,
                "write_tools_allowed": False,
            },
            context,
        )


class ApprovePlanTool:
    name = "approve_plan"
    description = (
        "Record the user's explicit decision for a Plan Artifact. Arguments: "
        "plan_id and approved boolean. Only approval enables execution tools."
    )

    def __init__(self, controller: PlanController) -> None:
        self.controller = controller

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "plan_id")
        if not isinstance(arguments.get("approved"), bool):
            raise ToolValidationError("approved must be a boolean")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        artifact = self.controller.store.decide(
            self.controller.scope_id,
            require_string(arguments, "plan_id"),
            approve=bool(arguments["approved"]),
        )
        return _result(
            {
                "plan": artifact.to_dict(),
                "write_tools_allowed": artifact.status is PlanPhase.EXECUTING,
            },
            context,
        )


class AskUserQuestionTool:
    name = "ask_user_question"
    description = (
        "Create a persisted user interaction request. Arguments: prompt, optional "
        "options and allow_free_text. Never invent an answer."
    )

    def __init__(self, controller: PlanController) -> None:
        self.controller = controller

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "prompt")
        _string_list(arguments.get("options", []), "options")
        if not isinstance(arguments.get("allow_free_text", True), bool):
            raise ToolValidationError("allow_free_text must be a boolean")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        question = self.controller.store.ask(
            self.controller.scope_id,
            prompt=require_string(arguments, "prompt"),
            options=_string_list(arguments.get("options", []), "options"),
            allow_free_text=bool(arguments.get("allow_free_text", True)),
        )
        rendered, was_truncated = truncate(
            json.dumps(
                {
                    "interaction_required": True,
                    "question": question.to_dict(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            context.output_limit,
        )
        return ToolResult(
            False,
            rendered,
            "interaction_required",
            {"question_id": question.question_id, "result_truncated": was_truncated},
        )


class AnswerUserQuestionTool:
    name = "answer_user_question"
    description = (
        "Record an explicit user answer to a pending question. Arguments: "
        "question_id and answer."
    )

    def __init__(self, controller: PlanController) -> None:
        self.controller = controller

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "question_id")
        require_string(arguments, "answer")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        question = self.controller.store.answer(
            require_string(arguments, "question_id"),
            require_string(arguments, "answer"),
        )
        return _result({"question": question.to_dict()}, context)


class PlanGuardedTool:
    """Deny mutating operations while planning or awaiting approval."""

    def __init__(self, inner: Any, controller: PlanController) -> None:
        self._inner = inner
        self._controller = controller
        self.name = inner.name
        self.description = (
            inner.description
            + " Plan Mode guard: unavailable while planning or awaiting approval."
        )

    def validate(self, arguments: dict[str, Any]) -> None:
        if self._controller.phase in {
            PlanPhase.PLANNING,
            PlanPhase.AWAITING_APPROVAL,
            PlanPhase.REJECTED,
        }:
            raise ToolValidationError(
                f"{self.name} denied by Plan Mode; explicit approval is required"
            )
        self._inner.validate(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return self._inner.execute(arguments, context)


def compose_plan_registry(
    registry: ToolRegistry,
    controller: PlanController,
) -> ToolRegistry:
    tools = []
    for name in registry.names:
        tool = registry.get(name)
        tools.append(
            PlanGuardedTool(tool, controller) if name in _MUTATING_TOOLS else tool
        )
    tools.extend(
        [
            EnterPlanModeTool(controller),
            ExitPlanModeTool(controller),
            ApprovePlanTool(controller),
            AskUserQuestionTool(controller),
            AnswerUserQuestionTool(controller),
        ]
    )
    return ToolRegistry(tools)


def _string_list(value: Any, name: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ToolValidationError(f"{name} must be a list of strings")
    values = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(values) != len(value):
        raise ToolValidationError(f"{name} must contain non-empty strings")
    if required and not values:
        raise ToolValidationError(f"{name} must not be empty")
    return values


def _result(payload: dict[str, Any], context: ToolContext) -> ToolResult:
    rendered, was_truncated = truncate(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        context.output_limit,
    )
    return ToolResult(True, rendered, metadata={"result_truncated": was_truncated})


__all__ = [
    "AnswerUserQuestionTool",
    "ApprovePlanTool",
    "AskUserQuestionTool",
    "EnterPlanModeTool",
    "ExitPlanModeTool",
    "PlanController",
    "PlanGuardedTool",
    "compose_plan_registry",
]
