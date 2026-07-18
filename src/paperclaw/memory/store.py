"""Bounded, auditable long-term memory stores for PaperClaw.

The design deliberately keeps two human-readable files:

- ``MEMORY.md`` for project/environment lessons and durable working conventions;
- ``USER.md`` for user identity, preferences, communication style and expectations.

Writes are explicit and atomic. Capacity overflow is rejected rather than silently
truncating older entries. Expired entries remain on disk for auditability but are
excluded from prompt snapshots until the user removes or replaces them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Iterable, Literal
from uuid import uuid4

MemoryTarget = Literal["memory", "user"]

_MEMORY_CATEGORIES = frozenset(
    {"environment", "project", "convention", "lesson", "task", "other"}
)
_USER_CATEGORIES = frozenset(
    {"identity", "preference", "communication", "workflow", "skill", "constraint", "other"}
)
_ENTRY_DELIMITER = "\n§\n"
_METADATA_PREFIX = "<!-- paperclaw-memory "
_METADATA_SUFFIX = " -->"
_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class MemoryStoreError(RuntimeError):
    """Base error for persistent-memory operations."""


class MemoryCapacityError(MemoryStoreError):
    """Raised when a write would exceed the configured bounded store."""


class MemoryMatchError(MemoryStoreError):
    """Raised when replace/remove substring matching is not unique."""


class MemoryPrivacyError(MemoryStoreError):
    """Raised when content appears to contain a credential or private key."""


@dataclass(frozen=True)
class MemoryPolicy:
    memory_char_limit: int = 2_200
    user_char_limit: int = 1_375
    max_entry_chars: int = 800
    max_entries: int = 64

    def __post_init__(self) -> None:
        for name, value in (
            ("memory_char_limit", self.memory_char_limit),
            ("user_char_limit", self.user_char_limit),
            ("max_entry_chars", self.max_entry_chars),
            ("max_entries", self.max_entries),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    def limit_for(self, target: MemoryTarget) -> int:
        return self.memory_char_limit if target == "memory" else self.user_char_limit


@dataclass(frozen=True)
class MemoryEntry:
    entry_id: str
    target: MemoryTarget
    category: str
    content: str
    confidence: float
    source: str
    created_at: str
    updated_at: str
    expires_at: str | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires <= datetime.now(timezone.utc)

    def to_metadata(self) -> dict[str, object]:
        return {
            "id": self.entry_id,
            "target": self.target,
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "content_sha256": self.content_hash,
        }


@dataclass(frozen=True)
class MemorySnapshot:
    memory_entries: tuple[MemoryEntry, ...]
    user_entries: tuple[MemoryEntry, ...]
    memory_used_chars: int
    user_used_chars: int
    memory_limit_chars: int
    user_limit_chars: int
    fingerprint: str

    def entries_for(self, target: MemoryTarget) -> tuple[MemoryEntry, ...]:
        return self.memory_entries if target == "memory" else self.user_entries


class FileMemoryStore:
    """Atomic file-backed memory with deterministic parsing and bounded writes."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        policy: MemoryPolicy | None = None,
    ) -> None:
        self.root = Path(root or Path.home() / ".paperclaw" / "memories").expanduser()
        self.policy = policy or MemoryPolicy()
        self._lock = threading.RLock()

    def path_for(self, target: MemoryTarget) -> Path:
        self._validate_target(target)
        return self.root / ("MEMORY.md" if target == "memory" else "USER.md")

    def list_entries(
        self,
        target: MemoryTarget,
        *,
        include_expired: bool = False,
    ) -> tuple[MemoryEntry, ...]:
        with self._lock:
            entries = tuple(self._read(target))
        if include_expired:
            return entries
        return tuple(entry for entry in entries if not entry.is_expired)

    def snapshot(self) -> MemorySnapshot:
        """Capture the frozen prompt snapshot used for one runtime/session."""

        memory = self.list_entries("memory")
        user = self.list_entries("user")
        memory_used = self._content_chars(memory)
        user_used = self._content_chars(user)
        payload = {
            "memory": [entry.to_metadata() for entry in memory],
            "user": [entry.to_metadata() for entry in user],
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return MemorySnapshot(
            memory_entries=memory,
            user_entries=user,
            memory_used_chars=memory_used,
            user_used_chars=user_used,
            memory_limit_chars=self.policy.memory_char_limit,
            user_limit_chars=self.policy.user_char_limit,
            fingerprint=fingerprint,
        )

    def add(
        self,
        target: MemoryTarget,
        content: str,
        *,
        category: str = "other",
        confidence: float = 0.8,
        ttl_days: int | None = None,
        source: str = "agent_curated",
    ) -> MemoryEntry:
        normalized = self._validate_content(content)
        normalized_category = self._validate_category(target, category)
        normalized_confidence = self._validate_confidence(confidence)
        expires_at = self._expires_at(ttl_days)
        now = self._now()
        with self._lock:
            entries = self._read(target)
            duplicate = next(
                (
                    entry
                    for entry in entries
                    if self._normalize_for_match(entry.content)
                    == self._normalize_for_match(normalized)
                ),
                None,
            )
            if duplicate is not None:
                return duplicate
            if len(entries) >= self.policy.max_entries:
                raise MemoryCapacityError(
                    f"{target} memory already contains {self.policy.max_entries} entries"
                )
            entry = MemoryEntry(
                entry_id=f"{target}-{uuid4().hex[:16]}",
                target=target,
                category=normalized_category,
                content=normalized,
                confidence=normalized_confidence,
                source=self._validate_source(source),
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
            )
            updated = [*entries, entry]
            self._assert_capacity(target, updated)
            self._write(target, updated)
            return entry

    def replace(
        self,
        target: MemoryTarget,
        old_text: str,
        content: str,
        *,
        category: str | None = None,
        confidence: float | None = None,
        ttl_days: int | None = None,
    ) -> MemoryEntry:
        normalized = self._validate_content(content)
        with self._lock:
            entries = self._read(target)
            index = self._unique_match(entries, old_text)
            previous = entries[index]
            replacement = MemoryEntry(
                entry_id=previous.entry_id,
                target=target,
                category=(
                    previous.category
                    if category is None
                    else self._validate_category(target, category)
                ),
                content=normalized,
                confidence=(
                    previous.confidence
                    if confidence is None
                    else self._validate_confidence(confidence)
                ),
                source=previous.source,
                created_at=previous.created_at,
                updated_at=self._now(),
                expires_at=(
                    previous.expires_at
                    if ttl_days is None
                    else self._expires_at(ttl_days)
                ),
            )
            updated = list(entries)
            updated[index] = replacement
            self._assert_capacity(target, updated)
            self._write(target, updated)
            return replacement

    def remove(self, target: MemoryTarget, old_text: str) -> MemoryEntry:
        with self._lock:
            entries = self._read(target)
            index = self._unique_match(entries, old_text)
            removed = entries[index]
            updated = [entry for offset, entry in enumerate(entries) if offset != index]
            self._write(target, updated)
            return removed

    def usage(self, target: MemoryTarget) -> dict[str, int]:
        entries = self.list_entries(target, include_expired=True)
        return {
            "entries": len(entries),
            "used_chars": self._content_chars(entries),
            "limit_chars": self.policy.limit_for(target),
        }

    def _read(self, target: MemoryTarget) -> list[MemoryEntry]:
        path = self.path_for(target)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        entries: list[MemoryEntry] = []
        for block in text.split(_ENTRY_DELIMITER):
            block = block.strip()
            if not block:
                continue
            first, separator, content = block.partition("\n")
            if not separator or not first.startswith(_METADATA_PREFIX) or not first.endswith(
                _METADATA_SUFFIX
            ):
                raise MemoryStoreError(f"invalid memory entry format in {path}")
            raw_metadata = first[len(_METADATA_PREFIX) : -len(_METADATA_SUFFIX)]
            try:
                metadata = json.loads(raw_metadata)
            except json.JSONDecodeError as exc:
                raise MemoryStoreError(f"invalid memory metadata in {path}") from exc
            entry = MemoryEntry(
                entry_id=str(metadata["id"]),
                target=target,
                category=str(metadata.get("category", "other")),
                content=content.strip(),
                confidence=float(metadata.get("confidence", 0.8)),
                source=str(metadata.get("source", "unknown")),
                created_at=str(metadata.get("created_at", "")),
                updated_at=str(metadata.get("updated_at", "")),
                expires_at=(
                    str(metadata["expires_at"])
                    if metadata.get("expires_at") is not None
                    else None
                ),
            )
            entries.append(entry)
        return entries

    def _write(self, target: MemoryTarget, entries: Iterable[MemoryEntry]) -> None:
        path = self.path_for(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = _ENTRY_DELIMITER.join(self._render_entry(entry) for entry in entries)
        if rendered:
            rendered += "\n"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _render_entry(entry: MemoryEntry) -> str:
        metadata = {
            "id": entry.entry_id,
            "category": entry.category,
            "confidence": entry.confidence,
            "source": entry.source,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "expires_at": entry.expires_at,
        }
        return (
            f"{_METADATA_PREFIX}"
            f"{json.dumps(metadata, sort_keys=True, separators=(',', ':'))}"
            f"{_METADATA_SUFFIX}\n{entry.content}"
        )

    def _assert_capacity(
        self, target: MemoryTarget, entries: Iterable[MemoryEntry]
    ) -> None:
        used = self._content_chars(entries)
        limit = self.policy.limit_for(target)
        if used > limit:
            raise MemoryCapacityError(
                f"{target} memory would use {used}/{limit} characters; "
                "consolidate or remove an entry before retrying"
            )

    @staticmethod
    def _content_chars(entries: Iterable[MemoryEntry]) -> int:
        values = tuple(entries)
        if not values:
            return 0
        return sum(len(entry.content) for entry in values) + max(0, len(values) - 1)

    def _validate_content(self, content: str) -> str:
        if not isinstance(content, str):
            raise TypeError("memory content must be a string")
        normalized = "\n".join(line.rstrip() for line in content.strip().splitlines())
        if not normalized:
            raise ValueError("memory content must not be empty")
        if len(normalized) > self.policy.max_entry_chars:
            raise ValueError(
                f"memory entry exceeds max_entry_chars={self.policy.max_entry_chars}"
            )
        if any(pattern.search(normalized) for pattern in _SECRET_PATTERNS):
            raise MemoryPrivacyError(
                "memory content appears to contain a credential or private key"
            )
        return normalized

    @staticmethod
    def _validate_target(target: str) -> None:
        if target not in {"memory", "user"}:
            raise ValueError("target must be memory or user")

    @staticmethod
    def _validate_confidence(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("confidence must be numeric")
        normalized = float(value)
        if not 0 <= normalized <= 1:
            raise ValueError("confidence must be within [0, 1]")
        return normalized

    @staticmethod
    def _validate_source(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("source must be a non-empty string")
        return value.strip()[:80]

    @staticmethod
    def _validate_category(target: MemoryTarget, category: str) -> str:
        if not isinstance(category, str):
            raise TypeError("category must be a string")
        normalized = category.strip().lower()
        allowed = _MEMORY_CATEGORIES if target == "memory" else _USER_CATEGORIES
        if normalized not in allowed:
            raise ValueError(
                f"unsupported {target} category: {normalized}; allowed={sorted(allowed)}"
            )
        return normalized

    @staticmethod
    def _unique_match(entries: list[MemoryEntry], old_text: str) -> int:
        needle = FileMemoryStore._normalize_for_match(old_text)
        if not needle:
            raise MemoryMatchError("old_text must not be empty")
        matches = [
            index
            for index, entry in enumerate(entries)
            if needle in FileMemoryStore._normalize_for_match(entry.content)
        ]
        if not matches:
            raise MemoryMatchError("old_text did not match any memory entry")
        if len(matches) > 1:
            raise MemoryMatchError(
                "old_text matched multiple entries; use a more specific substring"
            )
        return matches[0]

    @staticmethod
    def _normalize_for_match(value: str) -> str:
        return " ".join(str(value).casefold().split())

    @staticmethod
    def _expires_at(ttl_days: int | None) -> str | None:
        if ttl_days is None:
            return None
        if isinstance(ttl_days, bool) or not isinstance(ttl_days, int) or ttl_days < 1:
            raise ValueError("ttl_days must be a positive integer")
        return (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = [
    "FileMemoryStore",
    "MemoryCapacityError",
    "MemoryEntry",
    "MemoryMatchError",
    "MemoryPolicy",
    "MemoryPrivacyError",
    "MemorySnapshot",
    "MemoryStoreError",
    "MemoryTarget",
]
