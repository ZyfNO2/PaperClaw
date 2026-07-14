from __future__ import annotations

import json
import re
from typing import Any

from .state import ToolCall
from .verification import DoneProposal, ReflectionDecision


class ActionParseError(ValueError):
    pass


def _load_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if not match:
            raise ActionParseError("model output must be exactly one JSON object")
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ActionParseError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ActionParseError("model output must be a JSON object")
    return value


def parse_action(raw: str, allowed_tools: tuple[str, ...]) -> ToolCall | DoneProposal:
    value = _load_object(raw)
    action = value.get("action")
    if not isinstance(action, str):
        raise ActionParseError("action must be a string")
    if action == "done":
        args = value.get("arguments", {})
        if not isinstance(args, dict):
            raise ActionParseError("done.arguments must be an object")
        result = args.get("result")
        if not isinstance(result, str) or not result:
            raise ActionParseError("done.arguments.result must be a non-empty string")
        verification = args.get("verification") or ""
        issues = args.get("remaining_issues")
        if issues is None:
            issues = []
        elif isinstance(issues, str):
            issues = [issues]
        if not isinstance(verification, str) or not isinstance(issues, list) or not all(isinstance(x, str) for x in issues):
            raise ActionParseError("invalid done arguments")
        return DoneProposal(result, verification, issues)
    if action not in allowed_tools:
        raise ActionParseError(f"unknown action: {action}; allowed: {', '.join((*allowed_tools, 'done'))}")
    arguments = value.get("arguments")
    reason = value.get("reason", "")
    if not isinstance(arguments, dict) or not isinstance(reason, str):
        raise ActionParseError("arguments must be an object and reason must be a string")
    return ToolCall(action, arguments, reason)


def parse_reflection_decision(raw: str) -> ReflectionDecision:
    value = _load_object(raw)
    decision = value.get("decision")
    if decision not in {"accept", "continue", "repair", "reverify", "blocked"}:
        raise ActionParseError("decision must be one of accept|continue|repair|reverify|blocked")
    evidence_ids = value.get("evidence_ids", [])
    failed_claim_ids = value.get("failed_claim_ids", [])
    next_action = value.get("next_action")
    reason_code = value.get("reason_code")
    confidence = value.get("confidence")
    if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
        raise ActionParseError("evidence_ids must be a list of strings")
    if not isinstance(failed_claim_ids, list) or not all(isinstance(item, str) for item in failed_claim_ids):
        raise ActionParseError("failed_claim_ids must be a list of strings")
    if next_action is not None and not isinstance(next_action, str):
        raise ActionParseError("next_action must be a string or null")
    if not isinstance(reason_code, str) or not reason_code:
        raise ActionParseError("reason_code must be a non-empty string")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ActionParseError("confidence must be in [0, 1]")
    return ReflectionDecision(decision, evidence_ids, failed_claim_ids, next_action, reason_code, float(confidence))


def validate_reflection_decision(decision: ReflectionDecision, verification_result) -> ReflectionDecision:
    """Reject reflection outputs that try to outvote Verify instead of responding to it.

    Reflection is advisory over immutable evidence. It may choose the next route, but it may not reference fabricated
    evidence ids, accept a failed verification result, or silently drop required failed claims from the decision
    payload.
    """

    evidence_ids = {check.evidence_id for check in verification_result.checks}
    if any(evidence_id not in evidence_ids for evidence_id in decision.evidence_ids):
        raise ActionParseError("reflection decision referenced unknown evidence ids")
    if decision.decision == "accept" and verification_result.status != "passed":
        raise ActionParseError("reflection cannot accept a verification result that is not passed")
    required_failed_claim_ids = sorted(verification_result.failed_claim_ids)
    if required_failed_claim_ids and decision.decision != "accept":
        if sorted(decision.failed_claim_ids) != required_failed_claim_ids:
            raise ActionParseError("reflection must preserve all required failed claim ids")
    return decision
