from __future__ import annotations

import json

from paperclaw.models.base import ModelTurn


class FakeModel:
    def __init__(self, actions: list[dict | str]) -> None:
        self.actions = iter(actions)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        value = next(self.actions)
        content = value if isinstance(value, str) else json.dumps(value)
        return ModelTurn(content=content)


def action(name: str, arguments: dict, reason: str = "test") -> dict:
    return {"action": name, "arguments": arguments, "reason": reason}


def done(result: str = "complete", verification: str = "verified by command") -> dict:
    return action("done", {"result": result, "verification": verification, "remaining_issues": []})


def reflect(decision: str, *, reason_code: str = "test_decision", confidence: float = 0.9, next_action: str | None = None, evidence_ids: list[str] | None = None, failed_claim_ids: list[str] | None = None) -> dict:
    return {
        "decision": decision,
        "evidence_ids": evidence_ids or [],
        "failed_claim_ids": failed_claim_ids or [],
        "next_action": next_action,
        "reason_code": reason_code,
        "confidence": confidence,
    }
