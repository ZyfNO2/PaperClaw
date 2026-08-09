"""L5 ContextCandidate source for frozen and recalled structured Memory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from paperclaw.context.orchestration import ContextCandidate, ContextRequest, estimate_tokens

from .contracts import MemoryItem, MemoryScope, MemorySnapshot
from .service import MemoryService


class StructuredMemoryContextSource:
    """Expose Memory as L5 without changing L0-L4 semantics.

    Pinned items come only from the immutable session snapshot.  Recall items
    are queried per turn from the exact USER/PROJECT scopes and are marked
    separately in metadata so prompt stability tests can distinguish them.
    """

    def __init__(
        self,
        service: MemoryService,
        *,
        snapshot: MemorySnapshot | None,
        user_scope_id: str,
        project_scope_id: str | None = None,
        recall_top_k: int = 5,
        event_sink: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        if recall_top_k < 1:
            raise ValueError("recall_top_k must be positive")
        self.service = service
        self.snapshot = snapshot
        self.user_scope_id = user_scope_id
        self.project_scope_id = project_scope_id
        self.recall_top_k = recall_top_k
        self.event_sink = event_sink

    def collect(self, request: ContextRequest) -> tuple[ContextCandidate, ...]:
        if self.snapshot is None:
            self.snapshot = self.service.get_snapshot(request.conversation_id)
            if self.snapshot is None:
                # The executor normally captures this during Session start. A
                # direct source use still fails closed by capturing exactly
                # once for the requested conversation rather than reloading on
                # every turn.
                self.snapshot = self.service.capture_snapshot(
                    conversation_id=request.conversation_id,
                    user_scope_id=self.user_scope_id,
                    project_scope_id=self.project_scope_id,
                    event_sink=self.event_sink,
                )
        assert self.snapshot is not None
        pinned = self.service.snapshot_items(self.snapshot)
        candidates = [self._candidate(item, mode="pinned") for item in pinned]
        recalled = self.service.search_memory(
            request.raw_prompt,
            scopes=self._scopes(),
            top_k=self.recall_top_k,
            event_sink=self.event_sink,
        )
        pinned_ids = set(self.snapshot.memory_ids)
        candidates.extend(
            self._candidate(item, mode="retrieved")
            for item in recalled
            if item.memory_id not in pinned_ids
        )
        return tuple(candidates)

    def _scopes(self) -> tuple[tuple[str, str], ...]:
        scopes = [(MemoryScope.USER.value, self.user_scope_id)]
        if self.project_scope_id:
            scopes.append((MemoryScope.PROJECT.value, self.project_scope_id))
        return tuple(scopes)

    @staticmethod
    def _candidate(item: MemoryItem, *, mode: str) -> ContextCandidate:
        return ContextCandidate(
            candidate_id=f"memory:{item.memory_id}:{mode}",
            source="persistent_memory",
            source_ref=item.memory_id,
            layer="L5",
            kind=item.kind,
            scope=(f"memory:{item.scope_type}:{item.scope_id}",),
            priority=(900 if mode == "pinned" else 500) + item.importance,
            trust=item.trust_level,
            freshness=item.created_from_sequence or 0,
            estimated_tokens=estimate_tokens(item.content),
            content=item.content,
            bucket="protected" if mode == "pinned" else "retrieval",
            pinned=mode == "pinned",
            compressible=mode != "pinned",
            metadata={
                "memory_id": item.memory_id,
                "memory_mode": mode,
                "scope_type": item.scope_type,
                "scope_id": item.scope_id,
                "kind": item.kind,
                "content_hash": item.content_hash,
                "source_refs": list(item.source_refs),
                "trust_level": item.trust_level,
            },
        )


__all__ = ["StructuredMemoryContextSource"]
