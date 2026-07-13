from __future__ import annotations

from pocketflow import Node

from paperclaw.models.base import ChatModel
from paperclaw.tools.base import ToolContext, ToolResult, safe_execute
from paperclaw.tools.registry import ToolRegistry

from .events import emit_event
from .parser import ActionParseError, parse_action, parse_reflection_decision, validate_reflection_decision
from .prompts import build_prompt
from .reflect import accept_decision, build_reflection_prompt, register_failure_signature
from .state import HistoryEntry, ToolCall
from .verify import build_verification_plan, execute_verification_plan
from .verification import DoneProposal, ReflectionDecision


class DecideActionNode(Node):
    """Ask the model for exactly one next action and normalize malformed output into bounded retry behavior."""

    def __init__(self, model: ChatModel, registry: ToolRegistry, max_invalid_outputs: int = 2) -> None:
        super().__init__()
        self.model = model
        self.registry = registry
        self.max_invalid_outputs = max_invalid_outputs

    def prep(self, shared: dict) -> str | None:
        if shared["step_count"] >= shared["max_steps"]:
            return None
        cancel_event = shared.get("cancel_event")
        if cancel_event is not None and cancel_event.is_set():
            shared["stop_reason"] = "cancelled"
            return None
        return build_prompt(shared, self.registry)

    def exec(self, prompt: str | None):
        if prompt is None:
            return None
        turn = self.model.complete(prompt)
        return turn

    def post(self, shared: dict, prep_res, exec_res) -> str:
        if prep_res is None:
            if shared.get("stop_reason") == "cancelled":
                emit_event(shared, "stop", reason="cancelled", step=shared["step_count"])
                return "done"
            shared["stop_reason"] = "max_steps"
            emit_event(shared, "stop", reason="max_steps", step=shared["step_count"])
            return "done"
        shared["step_count"] += 1
        raw = exec_res.content
        # Reasoning is surfaced for debug visibility only; the runtime never treats it as trusted structured state.
        emit_event(shared, "model_call", step=shared["step_count"], model="decide")
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
        if isinstance(parsed, DoneProposal):
            shared["done_proposal"] = parsed
            shared["result"] = parsed.result
            shared["verification"] = parsed.claimed_verification
            # v0.01 uses a deliberately weak verification rule; later SOPs replace this with Verify/Reflection gates.
            has_successful_command = any(entry.tool == "bash" and entry.result.ok for entry in shared["history"])
            shared["verification_status"] = "verified" if parsed.claimed_verification and has_successful_command else "unverified"
            shared["remaining_issues"] = parsed.remaining_issues
            shared["stop_reason"] = "done"
            emit_event(
                shared,
                "done_proposed",
                step=shared["step_count"],
                result=parsed.result,
                verification=parsed.claimed_verification,
                verification_status=shared["verification_status"],
                remaining_issues=parsed.remaining_issues,
            )
            if not shared.get("verification_gate_enabled", False):
                emit_event(
                    shared,
                    "done",
                    step=shared["step_count"],
                    result=parsed.result,
                    verification=parsed.claimed_verification,
                    verification_status=shared["verification_status"],
                    remaining_issues=parsed.remaining_issues,
                )
            return "done"
        assert isinstance(parsed, ToolCall)
        shared["current_tool_call"] = parsed
        emit_event(shared, "tool_call", step=shared["step_count"], tool=parsed.action, arguments=parsed.arguments, reason=parsed.reason, raw=raw)
        return parsed.action


class ExecuteToolNode(Node):
    """Run one validated tool call and feed its structured result back into history for the next decision step."""

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


class VerifyDoneProposalNode(Node):
    """Convert a completion proposal into deterministic local evidence before the run is accepted."""

    def prep(self, shared: dict):
        proposal = shared["done_proposal"]
        assert proposal is not None
        plan = build_verification_plan(shared)
        return proposal, plan

    def exec(self, prep_res):
        _, plan = prep_res
        return plan

    def post(self, shared: dict, prep_res, exec_res) -> str:
        proposal, plan = prep_res
        shared["verification_plan"] = plan
        emit_event(shared, "verification_planned", step=shared["step_count"], plan=plan.to_dict())
        emit_event(shared, "verification_started", step=shared["step_count"], claim_count=len(plan.task_claims), check_count=len(plan.checks))
        result = execute_verification_plan(shared, plan)
        shared["verification_result"] = result
        shared["verification_status"] = "verified" if result.status == "passed" else "unverified"
        shared["verification"] = proposal.claimed_verification
        shared["remaining_issues"] = proposal.remaining_issues
        for check in result.checks:
            emit_event(shared, "verification_check_completed", step=shared["step_count"], evidence=check.to_dict())
        emit_event(shared, "verification_completed", step=shared["step_count"], result=result.to_dict())
        return "default"


class ReflectNode(Node):
    """Consume deterministic verification evidence and decide whether to accept, retry, or block the run."""

    def __init__(self, model: ChatModel) -> None:
        super().__init__()
        self.model = model

    def prep(self, shared: dict):
        result = shared["verification_result"]
        if result is None:
            return None
        if result.status == "passed":
            return accept_decision(result)
        shared["reflection_round_count"] += 1
        if shared["reflection_round_count"] > shared["max_reflection_rounds"]:
            return ReflectionDecision("blocked", [], result.failed_claim_ids, None, "reflection_limit", 1.0)
        if register_failure_signature(shared) >= shared["max_reflection_rounds"]:
            return ReflectionDecision("blocked", [], result.failed_claim_ids, None, "repeated_failure", 1.0)
        emit_event(shared, "reflection_started", step=shared["step_count"], round=shared["reflection_round_count"])
        return build_reflection_prompt(shared)

    def exec(self, prep_res):
        if prep_res is None:
            return None
        if isinstance(prep_res, ReflectionDecision):
            return prep_res
        turn = self.model.complete(prep_res)
        return turn

    def post(self, shared: dict, prep_res, exec_res) -> str:
        if prep_res is None:
            shared["stop_reason"] = "internal_error"
            emit_event(shared, "stop", reason="internal_error", step=shared["step_count"])
            return "done"
        if isinstance(exec_res, ReflectionDecision):
            decision = exec_res
        else:
            emit_event(shared, "model_call", step=shared["step_count"], model="reflect")
            try:
                decision = parse_reflection_decision(exec_res.content)
                decision = validate_reflection_decision(decision, shared["verification_result"])
            except ActionParseError as exc:
                shared["stop_reason"] = "internal_error"
                emit_event(shared, "stop", reason=f"invalid_reflection_output:{exc}", step=shared["step_count"])
                return "done"
        shared["reflection_decision"] = decision
        emit_event(shared, "reflection_completed", step=shared["step_count"], decision=decision.to_dict())
        if decision.decision == "accept":
            proposal = shared["done_proposal"]
            shared["stop_reason"] = "completed_verified"
            emit_event(shared, "done", step=shared["step_count"], result=proposal.result, verification=proposal.claimed_verification, verification_status="verified", remaining_issues=proposal.remaining_issues)
            return "done"
        if decision.decision in {"repair", "continue"}:
            shared["stop_reason"] = None
            return "default"
        if decision.decision == "reverify":
            return "reverify"
        shared["stop_reason"] = "blocked_environment" if decision.reason_code == "blocked_environment" else "verification_failed"
        emit_event(shared, "stop", reason=shared["stop_reason"], step=shared["step_count"])
        return "done"
