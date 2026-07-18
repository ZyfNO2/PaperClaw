"""Explicit project-knowledge lifecycle, stale policy and bounded watcher."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
from time import monotonic
from typing import Callable

from paperclaw.retrieval import SQLiteBM25Retriever

from .indexing import (
    ProjectIndexReport,
    ProjectIndexStatus,
    build_project_index,
    inspect_project_index,
    project_index_database,
)
from .manifest import ProjectManifest, ProjectManifestStore


class ProjectIndexPolicy(str, Enum):
    REQUIRE_CURRENT = "require_current"
    ALLOW_STALE = "allow_stale"
    DISABLED = "disabled"


class ProjectKnowledgeUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectKnowledgeSnapshot:
    policy: ProjectIndexPolicy
    status: ProjectIndexStatus
    retriever_available: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "policy": self.policy.value,
            "status": self.status.to_dict(),
            "retriever_available": self.retriever_available,
        }


class ProjectKnowledgeRuntime:
    def __init__(
        self,
        store: ProjectManifestStore,
        manifest: ProjectManifest,
        *,
        policy: ProjectIndexPolicy | str = ProjectIndexPolicy.REQUIRE_CURRENT,
        max_file_bytes: int = 5_000_000,
    ) -> None:
        self.store = store
        self.manifest = manifest
        self.policy = ProjectIndexPolicy(policy)
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        self.max_file_bytes = max_file_bytes

    def inspect(self) -> ProjectKnowledgeSnapshot:
        status = inspect_project_index(
            self.store,
            self.manifest,
            max_file_bytes=self.max_file_bytes,
        )
        return ProjectKnowledgeSnapshot(
            policy=self.policy,
            status=status,
            retriever_available=self._usable(status),
        )

    def rebuild(self) -> ProjectIndexReport:
        if self.policy is ProjectIndexPolicy.DISABLED:
            raise ProjectKnowledgeUnavailableError("project knowledge is disabled")
        return build_project_index(
            self.store,
            self.manifest,
            max_file_bytes=self.max_file_bytes,
        )

    def refresh_if_stale(self) -> tuple[ProjectKnowledgeSnapshot, bool]:
        before = self.inspect()
        if before.status.current:
            return before, False
        self.rebuild()
        return self.inspect(), True

    def create_retriever(self) -> SQLiteBM25Retriever | None:
        snapshot = self.inspect()
        if not snapshot.retriever_available:
            if self.policy is ProjectIndexPolicy.DISABLED:
                return None
            raise ProjectKnowledgeUnavailableError(
                f"project knowledge unavailable: {snapshot.status.reason}"
            )
        return SQLiteBM25Retriever(
            project_index_database(self.store, self.manifest)
        )

    def _usable(self, status: ProjectIndexStatus) -> bool:
        if self.policy is ProjectIndexPolicy.DISABLED:
            return False
        if self.policy is ProjectIndexPolicy.REQUIRE_CURRENT:
            return status.current
        return status.available


@dataclass(frozen=True)
class ProjectKnowledgeWatchEvent:
    previous_reason: str
    current_reason: str
    rebuilt: bool
    elapsed_seconds: float


class ProjectKnowledgeWatcher:
    """Explicit polling watcher; never starts implicitly with the Agent runtime."""

    def __init__(
        self,
        runtime: ProjectKnowledgeRuntime,
        *,
        poll_seconds: float = 1.0,
        rebuild_on_change: bool = False,
        on_event: Callable[[ProjectKnowledgeWatchEvent], None] | None = None,
    ) -> None:
        if poll_seconds < 0.05:
            raise ValueError("poll_seconds must be at least 0.05")
        self.runtime = runtime
        self.poll_seconds = poll_seconds
        self.rebuild_on_change = rebuild_on_change
        self.on_event = on_event
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last = runtime.inspect()

    def poll_once(self) -> ProjectKnowledgeWatchEvent | None:
        started = monotonic()
        current = self.runtime.inspect()
        changed = (
            current.status.reason != self._last.status.reason
            or current.status.expected_fingerprint
            != self._last.status.expected_fingerprint
            or current.status.indexed_fingerprint
            != self._last.status.indexed_fingerprint
        )
        if not changed:
            return None
        previous = self._last
        rebuilt = False
        if self.rebuild_on_change and not current.status.current:
            self.runtime.rebuild()
            current = self.runtime.inspect()
            rebuilt = True
        self._last = current
        event = ProjectKnowledgeWatchEvent(
            previous_reason=previous.status.reason,
            current_reason=current.status.reason,
            rebuilt=rebuilt,
            elapsed_seconds=max(0.0, monotonic() - started),
        )
        if self.on_event is not None:
            self.on_event(event)
        return event

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"paperclaw-project-watch-{self.runtime.manifest.project_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.poll_once()
            except Exception:
                # Watcher failures never mutate the running Agent implicitly.
                continue


__all__ = [
    "ProjectIndexPolicy",
    "ProjectKnowledgeRuntime",
    "ProjectKnowledgeSnapshot",
    "ProjectKnowledgeUnavailableError",
    "ProjectKnowledgeWatchEvent",
    "ProjectKnowledgeWatcher",
]
