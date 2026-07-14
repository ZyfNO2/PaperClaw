from __future__ import annotations

from pocketflow import Node

from paperclaw.models.base import ChatModel
from paperclaw.tools.base import ToolContext, ToolResult, safe_execute
from paperclaw.tools.registry import ToolRegistry

from .events import emit_event
from .parser import ActionParseError, parse_action
from .prompts import build_prompt
from .state import DoneAction, HistoryEntry, ToolCall


class DecideActionNode(Node):
    def __init__(self, model: ChatModel, registry: ToolRegistry, max_invalid_outputs: int = 2) -> None:
        super().__init__()
        self.model = model
        self.registry = registry
        self.max_invalid_outputs = max_invalid_outputs

    def prep(self, shared: dict) -> str | None:
        if shared["step_count"] >= shared["max_steps"]:
            return None
        return build_prompt(shared, self.registry)

    def exec(self, prompt: str | None):
        if prompt is None:
            return None
        turn = self.model.complete(prompt)
        return turn

    def post(self, shared: dict, prep_res, exec_res) -> str:
        if prep_res is None:
            shared["stop_reason"] = "max_steps"
            emit_event(shared, "stop", reason="max_steps", step=shared["step_count"])
            return "done"
        shared["step_count"] += 1
        raw = exec_res.content
        if exec_res.reasoning:
            emit_event(shared, "reasoning", step=shared["step_count"], reasoning=exec_res.reasoning)
        try:
            parsed = parse_action(raw, self.registry.names)
        except ActionParseError as exc:
            shared["invalid_output_count"] += 1
            shared["history"].append(HistoryEntry(shared["step_count"], "model_output", {}, "invalid model output", ToolResult(False, str(exc), "invalid_model_output")))
            emit_event(shared, "invalid_model_output", step=shared["step_count"], raw=raw, error=str(exc))
            if shared["invalid_output_count"] >= self.max_invalid_outputs:
                shared["stop_reason"] = "invalid_model_output"
                emit_event(shared, "stop", reason="invalid_model_output", step=shared["step_count"])
                return "done"
            return "retry"
        shared["invalid_output_count"] = 0
        if isinstance(parsed, DoneAction):
            shared["result"] = parsed.result
            shared["verification"] = parsed.verification
            has_successful_command = any(entry.tool == "bash" and entry.result.ok for entry in shared["history"])
            shared["verification_status"] = "verified" if parsed.verification and has_successful_command else "unverified"
            shared["remaining_issues"] = parsed.remaining_issues
            shared["stop_reason"] = "done"
            emit_event(
                shared,
                "done",
                step=shared["step_count"],
                result=parsed.result,
                verification=parsed.verification,
                verification_status=shared["verification_status"],
                remaining_issues=parsed.remaining_issues,
            )
            return "done"
        assert isinstance(parsed, ToolCall)
        shared["current_tool_call"] = parsed
        emit_event(shared, "tool_call", step=shared["step_count"], tool=parsed.action, arguments=parsed.arguments, reason=parsed.reason, raw=raw)
        return parsed.action


class ExecuteToolNode(Node):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__()
        self.registry = registry

    def prep(self, shared: dict):
        return shared["current_tool_call"], ToolContext(shared["workspace"])

    def exec(self, prep_res):
        call, context = prep_res
        return safe_execute(self.registry.get(call.action), call.arguments, context)

    def post(self, shared: dict, prep_res, exec_res: ToolResult) -> str:
        call, _ = prep_res
        shared["history"].append(HistoryEntry(shared["step_count"], call.action, call.arguments, call.reason, exec_res))
        shared["current_tool_call"] = None
        emit_event(
            shared,
            "tool_result",
            step=shared["step_count"],
            tool=call.action,
            ok=exec_res.ok,
            output=exec_res.output,
            error_code=exec_res.error_code,
            metadata=exec_res.metadata,
        )
        return "default"
