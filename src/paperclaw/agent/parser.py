from __future__ import annotations

import json
import re
from typing import Any

from .state import DoneAction, ToolCall


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


def parse_action(raw: str, allowed_tools: tuple[str, ...]) -> ToolCall | DoneAction:
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
        return DoneAction(result, verification, issues)
    if action not in allowed_tools:
        raise ActionParseError(f"unknown action: {action}; allowed: {', '.join((*allowed_tools, 'done'))}")
    arguments = value.get("arguments")
    reason = value.get("reason", "")
    if not isinstance(arguments, dict) or not isinstance(reason, str):
        raise ActionParseError("arguments must be an object and reason must be a string")
    return ToolCall(action, arguments, reason)
