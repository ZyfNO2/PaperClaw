"""Domain service for v0.39 structured persistent Memory."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import hashlib
import re
from typing import Any

from paperclaw.context.orchestration import estimate_tokens
from paperclaw.context.repository import Repository

from .contracts import (
    MemoryBoundaryError,
    MemoryContractError,
    MemoryItem,
    MemoryKind,
    MemoryScope,
    MemorySnapshot,
    MemoryTrustError,
)
from .repository import MemoryRepository

MemoryEventSink = Callable[[str, dict[str, Any]], Any]

_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password)\s*[:=]"
)
_SOURCE_BODY_MARKERS = (
    "-----begin ",
    "<transcript>",
    "raw_tool_output:",
    "artifact_body:",
    "evidence_body:",
)


@dataclass(frozen=True)
class MemoryBudget:
    """Independent bounded budgets for pinned USER and PROJECT Memory."""

    user_pinned_tokens: int = 500
    project_pinned_tokens: int = 1_000
    max_content_chars: int = 4_000
    max_source_refs: int = 16

    def __post_init__(self) -> None:
        for name, value in (
            ("user_pinned_tokens", self.user_pinned_tokens),
            ("project_pinned_tokens", self.project_pinned_tokens),
            ("max_content_chars", self.max_content_chars),
            ("max_source_refs", self.max_source_refs),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


class MemoryService:
    """Validate and mutate immutable Memory history through one boundary.

    The service never writes SQLite directly.  It delegates persistence to
    ``MemoryRepository`` and emits bounded audit payloads through the existing
    SessionService sink when one is supplied.
    """

    def __init__(
        self,
        repository: MemoryRepository | Repository,
        *,
        event_sink: MemoryEventSink | None = None,
        budget: MemoryBudget | None = None,
    ) -> None:
        self.repository = (
            repository if isinstance(repository, MemoryRepository) else MemoryRepository(repository)
        )
        self.event_sink = event_sink
        self.budget = budget or MemoryBudget()

    def add_memory(
        self,
        *,
        scope_type: str | MemoryScope,
        scope_id: str,
        kind: str | MemoryKind,
        content: str,
        source_refs: Iterable[str] = (),
        trust_level: str = "trusted_local",
        importance: int = 50,
        pinned: bool = False,
        created_from_run_id: str | None = None,
        created_from_sequence: int | None = None,
        explicit_user_confirmation: bool = False,
    ) -> MemoryItem:
        effective_trust = self._resolve_trust(
            trust_level,
            source_refs=source_refs,
            explicit_user_confirmation=explicit_user_confirmation,
        )
        normalized_content = self._validate_content(content)
        refs = tuple(source_refs)
        if len(refs) > self.budget.max_source_refs:
            raise MemoryBoundaryError("source_refs exceed the bounded Memory limit")
        item = MemoryItem(
            scope_type=scope_type,
            scope_id=scope_id,
            kind=kind,
            content=normalized_content,
            source_refs=refs,
            trust_level=effective_trust,
            importance=importance,
            pinned=pinned,
            created_from_run_id=created_from_run_id,
            created_from_sequence=created_from_sequence,
        )
        self.repository.add(item)
        self._audit("memory.added", self._item_payload(item))
        return item

    def replace_memory(
        self,
        memory_id: str,
        *,
        content: str,
        source_refs: Iterable[str] | None = None,
        trust_level: str | None = None,
        importance: int | None = None,
        pinned: bool | None = None,
        kind: str | MemoryKind | None = None,
        created_from_run_id: str | None = None,
        created_from_sequence: int | None = None,
        explicit_user_confirmation: bool = False,
    ) -> MemoryItem:
        previous = self._require_active(memory_id)
        refs = previous.source_refs if source_refs is None else tuple(source_refs)
        if len(refs) > self.budget.max_source_refs:
            raise MemoryBoundaryError("source_refs exceed the bounded Memory limit")
        effective_trust = self._resolve_trust(
            trust_level or previous.trust_level,
            source_refs=refs,
            explicit_user_confirmation=explicit_user_confirmation,
        )
        item = MemoryItem(
            scope_type=previous.scope_type,
            scope_id=previous.scope_id,
            kind=kind or previous.kind,
            content=self._validate_content(content),
            source_refs=refs,
            trust_level=effective_trust,
            importance=previous.importance if importance is None else importance,
            pinned=previous.pinned if pinned is None else pinned,
            created_from_run_id=created_from_run_id,
            created_from_sequence=created_from_sequence,
            supersedes_memory_id=previous.memory_id,
        )
        self.repository.add(item)
        self._audit(
            "memory.replaced",
            {**self._item_payload(item), "supersedes_memory_id": previous.memory_id},
        )
        return item

    def remove_memory(
        self,
        memory_id: str,
        *,
        created_from_run_id: str | None = None,
        created_from_sequence: int | None = None,
    ) -> MemoryItem:
        previous = self._require_active(memory_id)
        tombstone = MemoryItem(
            scope_type=previous.scope_type,
            scope_id=previous.scope_id,
            kind=previous.kind,
            content="[memory tombstone]",
            source_refs=previous.source_refs,
            trust_level=previous.trust_level,
            importance=previous.importance,
            pinned=False,
            created_from_run_id=created_from_run_id,
            created_from_sequence=created_from_sequence,
            supersedes_memory_id=previous.memory_id,
            tombstone=True,
        )
        self.repository.add(tombstone)
        self._audit(
            "memory.removed",
            {**self._item_payload(tombstone), "supersedes_memory_id": previous.memory_id},
        )
        return tombstone

    def list_memory(
        self,
        *,
        scope_type: str | MemoryScope,
        scope_id: str,
        include_history: bool = False,
    ) -> list[MemoryItem]:
        normalized_scope = _scope_value(scope_type)
        active = self.repository.list_active(normalized_scope, scope_id)
        if not include_history:
            return active
        return self.repository.list_all(normalized_scope, scope_id)

    def search_memory(
        self,
        query: str,
        *,
        scopes: Iterable[tuple[str | MemoryScope, str]],
        top_k: int = 10,
    ) -> list[MemoryItem]:
        if not isinstance(query, str) or not query.strip():
            return []
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise MemoryContractError("top_k must be a positive integer")
        results: list[MemoryItem] = []
        seen: set[str] = set()
        for scope_type, scope_id in scopes:
            normalized_scope = _scope_value(scope_type)
            for item in self.repository.search(
                query.strip(), normalized_scope, scope_id, limit=top_k
            ):
                if item.memory_id not in seen:
                    seen.add(item.memory_id)
                    results.append(item)
        results = results[:top_k]
        self._audit(
            "memory.retrieved",
            {
                "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                "result_count": len(results),
                "memory_ids": [item.memory_id for item in results],
            },
        )
        return results

    def capture_snapshot(
        self,
        *,
        conversation_id: str,
        user_scope_id: str,
        project_scope_id: str | None = None,
        event_sink: MemoryEventSink | None = None,
    ) -> MemorySnapshot:
        """Capture active pinned Memory once for a Conversation.

        Ordering and budget trimming are deterministic.  The persisted
        ``rendered_content`` and hash are the frozen prompt-prefix source for
        the entire Conversation; later writes only affect future snapshots.
        """
        pinned: list[MemoryItem] = []
        for scope_type, scope_id in (
            ((MemoryScope.USER.value, user_scope_id)),
            *((((MemoryScope.PROJECT.value, project_scope_id),) if project_scope_id else ())),
        ):
            candidates = self.repository.list_active(scope_type, scope_id)
            pinned.extend(item for item in candidates if item.pinned)

        user_budget = self.budget.user_pinned_tokens
        project_budget = self.budget.project_pinned_tokens
        selected: list[MemoryItem] = []
        used = {MemoryScope.USER.value: 0, MemoryScope.PROJECT.value: 0}
        for item in sorted(
            pinned,
            key=lambda value: (
                0 if value.scope_type == MemoryScope.USER.value else 1,
                -value.importance,
                value.kind,
                value.created_at,
                value.memory_id,
            ),
        ):
            budget = user_budget if item.scope_type == MemoryScope.USER.value else project_budget
            tokens = estimate_tokens(item.content)
            if used[item.scope_type] + tokens > budget:
                continue
            selected.append(item)
            used[item.scope_type] += tokens

        rendered = self._render_pinned(selected)
        snapshot = MemorySnapshot(
            conversation_id=conversation_id,
            user_scope_id=user_scope_id,
            project_scope_id=project_scope_id,
            memory_ids=tuple(item.memory_id for item in selected),
            rendered_content=rendered,
            rendered_hash=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            estimated_tokens=estimate_tokens(rendered),
        )
        self.repository.insert_snapshot(snapshot)
        self._audit(
            "memory.snapshot_created",
            {
                "snapshot_id": snapshot.snapshot_id,
                "conversation_id": conversation_id,
                "memory_ids": list(snapshot.memory_ids),
                "rendered_hash": snapshot.rendered_hash,
                "estimated_tokens": snapshot.estimated_tokens,
            },
            event_sink=event_sink,
        )
        return snapshot

    def get_snapshot(self, conversation_id: str) -> MemorySnapshot | None:
        return self.repository.get_snapshot(conversation_id)

    def snapshot_items(self, snapshot: MemorySnapshot) -> tuple[MemoryItem, ...]:
        items: list[MemoryItem] = []
        for memory_id in snapshot.memory_ids:
            item = self.repository.get(memory_id)
            if item is None:
                raise MemoryContractError(
                    f"frozen snapshot references missing memory_id={memory_id}"
                )
            items.append(item)
        return tuple(items)

    def _require_active(self, memory_id: str) -> MemoryItem:
        item = self.repository.get(memory_id)
        if item is None:
            raise MemoryContractError(f"unknown memory_id={memory_id}")
        active_ids = {
            current.memory_id
            for current in self.repository.list_active(item.scope_type, item.scope_id)
        }
        if item.memory_id not in active_ids:
            raise MemoryContractError("memory_id is historical or already tombstoned")
        return item

    def _validate_content(self, content: str) -> str:
        if not isinstance(content, str) or not content.strip():
            raise MemoryContractError("content must be non-empty")
        normalized = content.strip()
        if len(normalized) > self.budget.max_content_chars:
            raise MemoryBoundaryError("Memory content exceeds the bounded durable limit")
        lowered = normalized.casefold()
        if _SECRET_PATTERN.search(normalized) or any(
            marker in lowered for marker in _SOURCE_BODY_MARKERS
        ):
            raise MemoryBoundaryError(
                "Memory accepts compact durable conclusions or references, not secrets/source bodies"
            )
        return normalized

    @staticmethod
    def _resolve_trust(
        trust_level: str,
        *,
        source_refs: Iterable[str],
        explicit_user_confirmation: bool,
    ) -> str:
        if trust_level == "external_untrusted":
            if not explicit_user_confirmation:
                raise MemoryTrustError(
                    "external_untrusted content requires trusted Evidence or explicit user confirmation"
                )
            return "user"
        if any(str(ref).strip().casefold().startswith("external:") for ref in source_refs):
            if not explicit_user_confirmation:
                raise MemoryTrustError(
                    "external source cannot be promoted to persistent trusted Memory"
                )
        return trust_level

    def _audit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_sink: MemoryEventSink | None = None,
    ) -> None:
        sink = event_sink or self.event_sink
        if sink is None:
            return
        bounded = dict(payload)
        bounded.setdefault("schema_version", 1)
        sink(event_type, bounded)

    @staticmethod
    def _item_payload(item: MemoryItem) -> dict[str, Any]:
        return {
            "memory_id": item.memory_id,
            "scope_type": item.scope_type,
            "scope_id": item.scope_id,
            "kind": item.kind,
            "content_hash": item.content_hash,
            "source_refs": list(item.source_refs),
            "trust_level": item.trust_level,
            "importance": item.importance,
            "pinned": item.pinned,
        }

    @staticmethod
    def _render_pinned(items: Iterable[MemoryItem]) -> str:
        blocks = [
            "\n".join(
                (
                    f"[{item.memory_id}] scope={item.scope_type}:{item.scope_id} "
                    f"kind={item.kind} trust={item.trust_level}",
                    item.content,
                )
            )
            for item in items
        ]
        return "\n\n".join(blocks)


def _scope_value(value: str | MemoryScope) -> str:
    if isinstance(value, MemoryScope):
        return value.value
    normalized = str(value).strip().upper()
    try:
        return MemoryScope(normalized).value
    except ValueError as exc:
        raise MemoryContractError(
            f"unsupported memory scope {normalized!r}; expected USER or PROJECT"
        ) from exc


__all__ = ["MemoryBudget", "MemoryService"]
