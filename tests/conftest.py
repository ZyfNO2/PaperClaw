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
