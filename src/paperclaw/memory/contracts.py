"""Structured persistent-memory contracts for PaperClaw v0.39.

These contracts intentionally live beside the pre-v0.39 file-backed memory
compatibility layer.  The structured runtime has a different lifecycle and is
persisted through the existing Context/Session SQLite repository.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Iterable
from uuid import uuid4

from paperclaw.context.contracts import TRUST_LEVELS


class MemoryScope(str, Enum):
    """Scopes supported by the v0.39 MVP."""

    USER = "USER"
    PROJECT = "PROJECT"


class MemoryKind(str, Enum):
    """Bounded vocabulary for durable MemoryItem knowledge."""

    USER_PREFERENCE = "user_preference"
    PROJECT_FACT = "project_fact"
    DECISION = "decision"
    CONSTRAINT = "constraint"
    WORKFLOW = "workflow"
    LESSON = "lesson"


class MemoryConflictDecision(str, Enum):
    """Explicit resolution choices for competing durable-memory candidates."""

    KEEP_BOTH = "keep_both"
    SUPERSEDE = "supersede"
    MERGE = "merge"
    REJECT_CANDIDATE = "reject_candidate"


@dataclass(frozen=True)
class MemorySourceRef:
    """Typed provenance that can be projected to the legacy string ref field."""

    source_type: str
    source_id: str
    locator: str | None = None

    def __post_init__(self) -> None:
        if not self.source_type.strip() or not self.source_id.strip():
            raise MemoryContractError("MemorySourceRef requires type and id")

    @property
    def ref(self) -> str:
        suffix = f"#{self.locator}" if self.locator else ""
        return f"{self.source_type.strip().lower()}:{self.source_id.strip()}{suffix}"

    def to_dict(self) -> dict[str, str]:
        data = {"source_type": self.source_type, "source_id": self.source_id}
        if self.locator:
            data["locator"] = self.locator
        return data


SUPPORTED_MEMORY_SCOPES = frozenset(item.value for item in MemoryScope)
SUPPORTED_MEMORY_KINDS = frozenset(item.value for item in MemoryKind)


class MemoryContractError(ValueError):
    """Raised when a structured Memory contract is invalid."""


class MemoryTrustError(MemoryContractError):
    """Raised when a Memory write would silently promote source trust."""


class MemoryBoundaryError(MemoryContractError):
    """Raised when Memory is used as an unbounded source-object store."""


@dataclass(frozen=True)
class MemoryConflictDecisionRecord:
    """Durable, append-only record of a Memory conflict decision."""

    candidate_memory_id: str
    conflicting_memory_ids: tuple[str, ...]
    decision: str | MemoryConflictDecision
    source_refs: tuple[str | MemorySourceRef, ...] = ()
    decision_id: str = field(default_factory=lambda: f"mdec-{uuid4().hex}")
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            resolved = (
                self.decision
                if isinstance(self.decision, MemoryConflictDecision)
                else MemoryConflictDecision(str(self.decision))
            )
        except ValueError as exc:
            raise MemoryContractError(
                f"unsupported conflict decision: {self.decision!r}"
            ) from exc
        if not self.candidate_memory_id.strip():
            raise MemoryContractError("candidate_memory_id must be non-empty")
        conflicts = tuple(dict.fromkeys(self.conflicting_memory_ids))
        if not conflicts:
            raise MemoryContractError("at least one conflicting memory is required")
        if any(not item.strip() for item in conflicts):
            raise MemoryContractError("conflicting memory ids must be non-empty")
        refs = _normalize_refs(self.source_refs)
        object.__setattr__(self, "decision", resolved.value)
        object.__setattr__(self, "conflicting_memory_ids", conflicts)
        object.__setattr__(self, "source_refs", refs)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["conflicting_memory_ids"] = list(self.conflicting_memory_ids)
        data["source_refs"] = list(self.source_refs)
        return data


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_refs(values: Iterable[str | MemorySourceRef]) -> tuple[str, ...]:
    refs: list[str] = []
    for value in values:
        if isinstance(value, MemorySourceRef):
            normalized = value.ref
        elif isinstance(value, str) and value.strip():
            normalized = value.strip()
        else:
            raise MemoryContractError("source_refs must contain non-empty strings")
        if len(normalized) > 512 or "\n" in normalized or "\r" in normalized:
            raise MemoryContractError("source_refs contain an invalid reference")
        refs.append(normalized)
    return tuple(dict.fromkeys(refs))


@dataclass(frozen=True)
class MemoryItem:
    """One immutable durable-memory record.

    Replacement and deletion never mutate an existing instance.  A new item
    points at its predecessor through ``supersedes_memory_id``; a tombstone is
    a history record and is never rendered as durable knowledge.
    """

    scope_type: str
    scope_id: str
    kind: str
    content: str
    memory_id: str = field(default_factory=lambda: f"mem-{uuid4().hex}")
    source_refs: tuple[str | MemorySourceRef, ...] = ()
    trust_level: str = "trusted_local"
    importance: int = 50
    pinned: bool = False
    created_from_run_id: str | None = None
    created_from_sequence: int | None = None
    supersedes_memory_id: str | None = None
    tombstone: bool = False
    content_hash: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        scope_type = _scope_value(self.scope_type)
        kind = _kind_value(self.kind)
        content = self.content.strip() if isinstance(self.content, str) else self.content
        if not isinstance(content, str) or not content:
            raise MemoryContractError("content must be non-empty")
        if not isinstance(self.scope_id, str) or not self.scope_id.strip():
            raise MemoryContractError("scope_id must be non-empty")
        if not isinstance(self.memory_id, str) or not self.memory_id.strip():
            raise MemoryContractError("memory_id must be non-empty")
        if self.trust_level not in TRUST_LEVELS:
            raise MemoryContractError(f"unsupported trust level: {self.trust_level}")
        if (
            isinstance(self.importance, bool)
            or not isinstance(self.importance, int)
            or not 0 <= self.importance <= 100
        ):
            raise MemoryContractError("importance must be an integer in [0, 100]")
        if not isinstance(self.pinned, bool) or not isinstance(self.tombstone, bool):
            raise MemoryContractError("pinned and tombstone must be booleans")
        if self.created_from_sequence is not None and (
            isinstance(self.created_from_sequence, bool)
            or not isinstance(self.created_from_sequence, int)
            or self.created_from_sequence < 0
        ):
            raise MemoryContractError("created_from_sequence must be non-negative")
        if self.supersedes_memory_id == self.memory_id:
            raise MemoryContractError("supersedes_memory_id must not equal memory_id")
        refs = _normalize_refs(self.source_refs)
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if self.content_hash and self.content_hash != expected_hash:
            raise MemoryContractError("content_hash does not match content")
        if not isinstance(self.created_at, str) or not self.created_at.strip():
            raise MemoryContractError("created_at must be a non-empty ISO timestamp")
        object.__setattr__(self, "scope_type", scope_type)
        object.__setattr__(self, "scope_id", self.scope_id.strip())
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "source_refs", refs)
        object.__setattr__(self, "content_hash", expected_hash)

    @property
    def active(self) -> bool:
        return not self.tombstone

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_refs"] = list(self.source_refs)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        payload = dict(data)
        payload["source_refs"] = tuple(payload.get("source_refs", ()))
        return cls(**payload)


@dataclass(frozen=True)
class MemorySnapshot:
    """Frozen pinned-memory projection bound to one Conversation."""

    conversation_id: str
    memory_ids: tuple[str, ...]
    rendered_content: str
    rendered_hash: str
    estimated_tokens: int
    created_at: str = field(default_factory=utc_now_iso)
    snapshot_id: str = field(default_factory=lambda: f"msnap-{uuid4().hex}")
    user_scope_id: str = "default-user"
    project_scope_id: str | None = None

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise MemoryContractError("conversation_id must be non-empty")
        if len(set(self.memory_ids)) != len(self.memory_ids):
            raise MemoryContractError("memory_ids must not contain duplicates")
        if self.estimated_tokens < 0:
            raise MemoryContractError("estimated_tokens must be non-negative")
        if not isinstance(self.rendered_content, str):
            raise MemoryContractError("rendered_content must be text")
        expected_hash = hashlib.sha256(
            self.rendered_content.encode("utf-8")
        ).hexdigest()
        if self.rendered_hash != expected_hash:
            raise MemoryContractError("rendered_hash does not match rendered_content")
        if not self.snapshot_id.strip():
            raise MemoryContractError("snapshot_id must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["memory_ids"] = list(self.memory_ids)
        return data


def _scope_value(value: str | MemoryScope) -> str:
    normalized = value.value if isinstance(value, MemoryScope) else str(value).strip().upper()
    if normalized not in SUPPORTED_MEMORY_SCOPES:
        raise MemoryContractError(
            f"unsupported memory scope {normalized!r}; expected USER or PROJECT"
        )
    return normalized


def _kind_value(value: str | MemoryKind) -> str:
    normalized = value.value if isinstance(value, MemoryKind) else str(value).strip().lower()
    if normalized not in SUPPORTED_MEMORY_KINDS:
        raise MemoryContractError(f"unsupported memory kind: {normalized!r}")
    return normalized


__all__ = [
    "MemoryBoundaryError",
    "MemoryContractError",
    "MemoryConflictDecision",
    "MemoryConflictDecisionRecord",
    "MemoryItem",
    "MemoryKind",
    "MemoryScope",
    "MemorySnapshot",
    "MemoryTrustError",
    "MemorySourceRef",
    "SUPPORTED_MEMORY_KINDS",
    "SUPPORTED_MEMORY_SCOPES",
]
