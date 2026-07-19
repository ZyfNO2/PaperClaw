"""Model-facing tool for curated long-term memory changes.

The tool intentionally exposes write operations only. The active prompt receives a
frozen snapshot captured when the runtime/session starts, so successful changes are
visible on the next session rather than mutating the current prompt prefix.
"""

from __future__ import annotations

import json
from typing import Any

from paperclaw.tools.base import ToolContext, ToolResult, ToolValidationError

from .scoped import MemoryStoreProtocol
from .store import FileMemoryStore, MemoryStoreError


class MemoryTool:
    name = "memory"
    description = (
        "Curate bounded long-term memory. Actions: add, replace, remove. "
        "Use target=user for stable user identity/preferences/communication/workflow; "
        "use target=memory for durable project/environment conventions and lessons. "
        "Do not store secrets, raw logs, transient paths, or easily rediscovered facts. "
        "Changes apply to the next runtime/session frozen snapshot."
    )

    def __init__(self, store: MemoryStoreProtocol | None = None) -> None:
        self.store: MemoryStoreProtocol = store or FileMemoryStore()

    def validate(self, arguments: dict[str, Any]) -> None:
        action = arguments.get("action")
        target = arguments.get("target")
        if action not in {"add", "replace", "remove"}:
            raise ToolValidationError("action must be add, replace, or remove")
        if target not in {"memory", "user"}:
            raise ToolValidationError("target must be memory or user")
        if action == "add":
            self._require_text(arguments, "content")
        elif action == "replace":
            self._require_text(arguments, "old_text")
            self._require_text(arguments, "content")
        else:
            self._require_text(arguments, "old_text")
        confidence = arguments.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise ToolValidationError("confidence must be numeric within [0, 1]")
        ttl_days = arguments.get("ttl_days")
        if ttl_days is not None and (
            isinstance(ttl_days, bool)
            or not isinstance(ttl_days, int)
            or ttl_days < 1
        ):
            raise ToolValidationError("ttl_days must be a positive integer")

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        del context
        action = str(arguments["action"])
        target = str(arguments["target"])
        try:
            if action == "add":
                entry = self.store.add(
                    target,  # type: ignore[arg-type]
                    str(arguments["content"]),
                    category=str(arguments.get("category", "other")),
                    confidence=float(arguments.get("confidence", 0.8)),
                    ttl_days=arguments.get("ttl_days"),
                )
                verb = "added"
            elif action == "replace":
                entry = self.store.replace(
                    target,  # type: ignore[arg-type]
                    str(arguments["old_text"]),
                    str(arguments["content"]),
                    category=(
                        str(arguments["category"])
                        if arguments.get("category") is not None
                        else None
                    ),
                    confidence=(
                        float(arguments["confidence"])
                        if arguments.get("confidence") is not None
                        else None
                    ),
                    ttl_days=arguments.get("ttl_days"),
                )
                verb = "replaced"
            else:
                entry = self.store.remove(
                    target,  # type: ignore[arg-type]
                    str(arguments["old_text"]),
                )
                verb = "removed"
        except (MemoryStoreError, TypeError, ValueError) as exc:
            return ToolResult(False, str(exc), "memory_write_failed")

        usage = self.store.usage(target)  # type: ignore[arg-type]
        payload = {
            "ok": True,
            "action": action,
            "target": target,
            "entry_id": entry.entry_id,
            "category": entry.category,
            "confidence": entry.confidence,
            "usage": usage,
            "snapshot_visibility": "next_session",
        }
        return ToolResult(
            True,
            json.dumps(payload, sort_keys=True),
            metadata={"verb": verb},
        )

    @staticmethod
    def _require_text(arguments: dict[str, Any], key: str) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ToolValidationError(f"{key} must be a non-empty string")
        return value


__all__ = ["MemoryTool"]
