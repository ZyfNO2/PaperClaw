"""Project-scoped memory routing with a global user profile."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Protocol

from .store import (
    FileMemoryStore,
    MemoryEntry,
    MemoryPolicy,
    MemorySnapshot,
    MemoryTarget,
)


class MemoryStoreProtocol(Protocol):
    def snapshot(self) -> MemorySnapshot: ...
    def add(self, target: MemoryTarget, content: str, **kwargs) -> MemoryEntry: ...
    def replace(
        self, target: MemoryTarget, old_text: str, content: str, **kwargs
    ) -> MemoryEntry: ...
    def remove(self, target: MemoryTarget, old_text: str) -> MemoryEntry: ...
    def usage(self, target: MemoryTarget) -> dict[str, int]: ...


@dataclass(frozen=True)
class ProjectMemoryPaths:
    global_root: Path
    project_root: Path


class ProjectScopedMemoryStore:
    """Route project lessons to a project namespace and user facts globally."""

    def __init__(
        self,
        global_root: str | Path,
        project_id: str,
        *,
        policy: MemoryPolicy | None = None,
    ) -> None:
        if not project_id or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_.-" for char in project_id):
            raise ValueError("project_id is not a safe memory namespace")
        resolved = Path(global_root).expanduser()
        self.paths = ProjectMemoryPaths(
            global_root=resolved,
            project_root=resolved / "projects" / project_id,
        )
        self.policy = policy or MemoryPolicy()
        self.global_store = FileMemoryStore(self.paths.global_root, policy=self.policy)
        self.project_store = FileMemoryStore(self.paths.project_root, policy=self.policy)
        self.project_id = project_id

    def _store_for(self, target: MemoryTarget) -> FileMemoryStore:
        if target == "memory":
            return self.project_store
        if target == "user":
            return self.global_store
        raise ValueError("target must be memory or user")

    def add(self, target: MemoryTarget, content: str, **kwargs) -> MemoryEntry:
        return self._store_for(target).add(target, content, **kwargs)

    def replace(
        self,
        target: MemoryTarget,
        old_text: str,
        content: str,
        **kwargs,
    ) -> MemoryEntry:
        return self._store_for(target).replace(target, old_text, content, **kwargs)

    def remove(self, target: MemoryTarget, old_text: str) -> MemoryEntry:
        return self._store_for(target).remove(target, old_text)

    def usage(self, target: MemoryTarget) -> dict[str, int]:
        return self._store_for(target).usage(target)

    def snapshot(self) -> MemorySnapshot:
        project = self.project_store.snapshot()
        global_user = self.global_store.snapshot()
        payload = {
            "project_id": self.project_id,
            "project_memory": [
                entry.to_metadata() for entry in project.memory_entries
            ],
            "global_user": [entry.to_metadata() for entry in global_user.user_entries],
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        return MemorySnapshot(
            memory_entries=project.memory_entries,
            user_entries=global_user.user_entries,
            memory_used_chars=project.memory_used_chars,
            user_used_chars=global_user.user_used_chars,
            memory_limit_chars=project.memory_limit_chars,
            user_limit_chars=global_user.user_limit_chars,
            fingerprint=fingerprint,
        )


__all__ = [
    "MemoryStoreProtocol",
    "ProjectMemoryPaths",
    "ProjectScopedMemoryStore",
]
