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
from .service import MemoryService


class MemoryTool:
    name = "memory"
    description = (
        "Curate bounded long-term memory. Actions: add, replace, remove. "
        "Use target=user for stable user identity/preferences/communication/workflow; "
        "use target=memory for durable project/environment conventions and lessons. "
        "Do not store secrets, raw logs, transient paths, or easily rediscovered facts. "
        "Changes apply to the next runtime/session frozen snapshot."
    )

    def __init__(
        self,
        store: MemoryStoreProtocol | MemoryService | None = None,
        *,
        service: MemoryService | None = None,
    ) -> None:
        self.service = service or (store if isinstance(store, MemoryService) else None)
        self.store: MemoryStoreProtocol | None = (
            None if self.service is not None else (store or FileMemoryStore())
        )

    def validate(self, arguments: dict[str, Any]) -> None:
        if self.service is not None:
            self._validate_structured(arguments)
            return
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
        if self.service is not None:
            return self._execute_structured(arguments)
        del context
        action = str(arguments["action"])
        target = str(arguments["target"])
        try:
            if action == "add":
                assert self.store is not None
                entry = self.store.add(
                    target,  # type: ignore[arg-type]
                    str(arguments["content"]),
                    category=str(arguments.get("category", "other")),
                    confidence=float(arguments.get("confidence", 0.8)),
                    ttl_days=arguments.get("ttl_days"),
                )
                verb = "added"
            elif action == "replace":
                assert self.store is not None
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
                assert self.store is not None
                entry = self.store.remove(
                    target,  # type: ignore[arg-type]
                    str(arguments["old_text"]),
                )
                verb = "removed"
        except (MemoryStoreError, TypeError, ValueError) as exc:
            return ToolResult(False, str(exc), "memory_write_failed")

        assert self.store is not None
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

    def _validate_structured(self, arguments: dict[str, Any]) -> None:
        action = arguments.get("action")
        if action not in {"add", "replace", "remove", "list", "search"}:
            raise ToolValidationError(
                "action must be add, replace, remove, list, or search"
            )
        if action == "add":
            for key in ("scope_type", "scope_id", "kind", "content"):
                self._require_text(arguments, key)
        elif action in {"replace", "remove"}:
            self._require_text(arguments, "memory_id")
            if action == "replace":
                self._require_text(arguments, "content")
        else:
            for key in ("scope_type", "scope_id"):
                self._require_text(arguments, key)
            if action == "search":
                self._require_text(arguments, "query")

    def _execute_structured(self, arguments: dict[str, Any]) -> ToolResult:
        assert self.service is not None
        action = str(arguments["action"])
        try:
            if action == "add":
                item = self.service.add_memory(
                    scope_type=str(arguments["scope_type"]),
                    scope_id=str(arguments["scope_id"]),
                    kind=str(arguments["kind"]),
                    content=str(arguments["content"]),
                    source_refs=tuple(arguments.get("source_refs", ())),
                    trust_level=str(arguments.get("trust_level", "trusted_local")),
                    importance=int(arguments.get("importance", 50)),
                    pinned=bool(arguments.get("pinned", False)),
                    explicit_user_confirmation=bool(
                        arguments.get("explicit_user_confirmation", False)
                    ),
                )
                payload = {"ok": True, "action": action, "memory": item.to_dict()}
            elif action == "replace":
                item = self.service.replace_memory(
                    str(arguments["memory_id"]),
                    content=str(arguments["content"]),
                    source_refs=(
                        tuple(arguments["source_refs"])
                        if "source_refs" in arguments
                        else None
                    ),
                    trust_level=(
                        str(arguments["trust_level"])
                        if "trust_level" in arguments
                        else None
                    ),
                    importance=(
                        int(arguments["importance"])
                        if "importance" in arguments
                        else None
                    ),
                    pinned=(bool(arguments["pinned"]) if "pinned" in arguments else None),
                    kind=(str(arguments["kind"]) if "kind" in arguments else None),
                    explicit_user_confirmation=bool(
                        arguments.get("explicit_user_confirmation", False)
                    ),
                )
                payload = {"ok": True, "action": action, "memory": item.to_dict()}
            elif action == "remove":
                item = self.service.remove_memory(str(arguments["memory_id"]))
                payload = {"ok": True, "action": action, "memory": item.to_dict()}
            elif action == "list":
                items = self.service.list_memory(
                    scope_type=str(arguments["scope_type"]),
                    scope_id=str(arguments["scope_id"]),
                )
                payload = {
                    "ok": True,
                    "action": action,
                    "memories": [item.to_dict() for item in items],
                }
            else:
                items = self.service.search_memory(
                    str(arguments["query"]),
                    scopes=((str(arguments["scope_type"]), str(arguments["scope_id"])),),
                    top_k=int(arguments.get("top_k", 10)),
                )
                payload = {
                    "ok": True,
                    "action": action,
                    "memories": [item.to_dict() for item in items],
                }
        except Exception as exc:
            return ToolResult(False, str(exc), "memory_operation_failed")
        return ToolResult(True, json.dumps(payload, ensure_ascii=False, sort_keys=True))


__all__ = ["MemoryTool"]
