"""Repository adapter for structured persistent Memory.

The adapter contains no domain policy and no SQL.  ``SQLiteRepository`` owns
the connection, migration, writer lock, and row serialization; this class
keeps the Memory domain boundary explicit for services and tools.
"""

from __future__ import annotations

from typing import Protocol

from paperclaw.context.repository import Repository

from .contracts import MemoryConflictDecisionRecord, MemoryItem, MemorySnapshot


class MemoryRepositoryProtocol(Protocol):
    def insert_memory_item(self, item: MemoryItem) -> None: ...
    def get_memory_item(self, memory_id: str) -> MemoryItem | None: ...
    def list_active_memory(self, scope_type: str, scope_id: str) -> list[MemoryItem]: ...
    def list_all_memory(self, scope_type: str, scope_id: str) -> list[MemoryItem]: ...
    def list_memory_history(self, memory_id: str) -> list[MemoryItem]: ...
    def search_memory_items(
        self, query: str, scope_type: str, scope_id: str, limit: int = 10
    ) -> list[MemoryItem]: ...
    def insert_memory_snapshot(self, snapshot: MemorySnapshot) -> None: ...
    def get_memory_snapshot(self, conversation_id: str) -> MemorySnapshot | None: ...
    def insert_memory_conflict_decision(
        self, decision: MemoryConflictDecisionRecord
    ) -> None: ...
    def list_memory_conflict_decisions(
        self, candidate_memory_id: str | None = None
    ) -> list[MemoryConflictDecisionRecord]: ...


class MemoryRepository:
    """Thin Memory-specific view over the existing Context Repository."""

    def __init__(self, repository: Repository | MemoryRepositoryProtocol):
        self._repository = repository

    @property
    def repository(self) -> Repository | MemoryRepositoryProtocol:
        return self._repository

    def add(self, item: MemoryItem) -> None:
        self._repository.insert_memory_item(item)

    def get(self, memory_id: str) -> MemoryItem | None:
        return self._repository.get_memory_item(memory_id)

    def list_active(self, scope_type: str, scope_id: str) -> list[MemoryItem]:
        return self._repository.list_active_memory(scope_type, scope_id)

    def list_all(self, scope_type: str, scope_id: str) -> list[MemoryItem]:
        return self._repository.list_all_memory(scope_type, scope_id)

    def list_history(self, memory_id: str) -> list[MemoryItem]:
        return self._repository.list_memory_history(memory_id)

    def search(
        self,
        query: str,
        scope_type: str,
        scope_id: str,
        *,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return self._repository.search_memory_items(query, scope_type, scope_id, limit)

    def insert_snapshot(self, snapshot: MemorySnapshot) -> None:
        self._repository.insert_memory_snapshot(snapshot)

    def get_snapshot(self, conversation_id: str) -> MemorySnapshot | None:
        return self._repository.get_memory_snapshot(conversation_id)

    def insert_conflict_decision(self, decision: MemoryConflictDecisionRecord) -> None:
        self._repository.insert_memory_conflict_decision(decision)

    def list_conflict_decisions(
        self, candidate_memory_id: str | None = None
    ) -> list[MemoryConflictDecisionRecord]:
        return self._repository.list_memory_conflict_decisions(candidate_memory_id)


__all__ = ["MemoryRepository", "MemoryRepositoryProtocol"]
