from __future__ import annotations

import json

from .verification import ReflectionDecision


def build_reflection_prompt(shared: dict) -> str:
    """Build a bounded reflection prompt from structured evidence only.

    Reflection sees the original task, the latest verification result, and recent history summaries. It does not see
    hidden reasoning or get permission to invent new acceptance criteria.
    """

    verification_result = shared["verification_result"]
    verification_plan = shared["verification_plan"]
    history = [entry.to_dict() for entry in shared["history"][-6:]]
    return "\n\n".join(
        [
            "[Identity]\nYou are the bounded reflection gate for one coding run.",
            "[Rules]\nUse only the supplied evidence. Do not relax required claims. Prefer the smallest next step. If evidence is sufficient, accept. If the same failure keeps repeating, block.",
            "[Task]\n" + shared["task"],
            "[Verification Plan]\n" + json.dumps(verification_plan.to_dict() if verification_plan else {}, ensure_ascii=False),
            "[Verification Result]\n" + json.dumps(verification_result.to_dict() if verification_result else {}, ensure_ascii=False),
            "[Recent History]\n" + json.dumps(history, ensure_ascii=False),
            "[Output Contract]\nReturn exactly one JSON object: {\"decision\":\"accept|continue|repair|reverify|blocked\",\"evidence_ids\":[],\"failed_claim_ids\":[],\"next_action\":\"short next step or null\",\"reason_code\":\"short_code\",\"confidence\":0.0}.",
        ]
    )


def failure_signature(shared: dict) -> str:
    """Collapse the latest verification failure into a stable signature for bounded retry tracking."""

    result = shared["verification_result"]
    if result is None:
        return "no-verification-result"
    return f"{result.status}|{','.join(result.failed_claim_ids)}|{','.join(result.uncovered_claim_ids)}"


def register_failure_signature(shared: dict) -> int:
    """Track consecutive identical verification failures to stop reflection loops from spinning indefinitely."""

    signature = failure_signature(shared)
    if shared.get("last_failure_signature") == signature:
        shared["failure_signature_count"] += 1
    else:
        shared["last_failure_signature"] = signature
        shared["failure_signature_count"] = 1
    return shared["failure_signature_count"]


def accept_decision(result) -> ReflectionDecision:
    evidence_ids = [check.evidence_id for check in result.checks]
    return ReflectionDecision("accept", evidence_ids, [], None, "verification_passed", 0.99)

