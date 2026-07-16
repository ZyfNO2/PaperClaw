"""Frozen contracts for the v0.09.1 RAG document/index foundation.

Phase A intentionally stops at document identity/versioning, deterministic
parsing/chunking and index persistence contracts. Retrieval ranking, Context
integration, citations and answer generation belong to later phases.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence
from urllib.parse import urlparse

PARSER_MARKDOWN = "markdown"
PARSER_PLAIN_TEXT = "plain_text"
PARSER_VERSION = "1"
INDEX_SCHEMA_VERSION = 1
INDEX_VERSION = "fts5-v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, *parts: str) -> str:
    digest = sha256_text(canonical_json(parts))
    return f"{prefix}_{digest[:24]}"


def compute_corpus_hash(chunks: Sequence["Chunk"]) -> str:
    """Hash the active chunk set independent of insertion order."""

    payload = [
        {
            "document_id": chunk.document_id,
            "version_id": chunk.version_id,
            "ordinal": chunk.ordinal,
            "content_hash": chunk.content_hash,
            "source_hash": chunk.source_hash,
            "chunk_config_hash": chunk.chunk_config_hash,
        }
        for chunk in sorted(
            chunks,
            key=lambda item: (item.document_id, item.version_id, item.ordinal, item.chunk_id),
        )
    ]
    return sha256_text(canonical_json(payload))


def _require_non_empty(name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _require_sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True)
class DocumentIdentity:
    """Stable identity for one logical local document."""

    document_id: str
    canonical_uri: str
    display_name: str
    source_type: Literal["local_file"] = "local_file"

    def __post_init__(self) -> None:
        _require_non_empty("document_id", self.document_id)
        _require_non_empty("canonical_uri", self.canonical_uri)
        _require_non_empty("display_name", self.display_name)
        parsed = urlparse(self.canonical_uri)
        if parsed.scheme != "file":
            raise ValueError("canonical_uri must use the file:// scheme in Phase A")

    @classmethod
    def from_file_uri(cls, canonical_uri: str, display_name: str) -> "DocumentIdentity":
        return cls(
            document_id=stable_id("doc", canonical_uri),
            canonical_uri=canonical_uri,
            display_name=display_name,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceArtifact:
    """Immutable source bytes and metadata used to create a document version."""

    artifact_id: str
    document_id: str
    source_uri: str
    media_type: str
    byte_length: int
    source_hash: str
    created_at: str

    def __post_init__(self) -> None:
        for name in ("artifact_id", "document_id", "source_uri", "media_type", "created_at"):
            _require_non_empty(name, getattr(self, name))
        if self.byte_length < 0:
            raise ValueError("byte_length must be non-negative")
        _require_sha256("source_hash", self.source_hash)

    @classmethod
    def from_bytes(
        cls,
        *,
        document_id: str,
        source_uri: str,
        media_type: str,
        content: bytes,
        created_at: str | None = None,
    ) -> "SourceArtifact":
        source_hash = sha256_bytes(content)
        return cls(
            artifact_id=stable_id("artifact", document_id, source_hash, source_uri),
            document_id=document_id,
            source_uri=source_uri,
            media_type=media_type,
            byte_length=len(content),
            source_hash=source_hash,
            created_at=created_at or utc_now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentVersion:
    """Immutable parser-specific version of a logical document."""

    version_id: str
    document_id: str
    source_artifact_id: str
    source_hash: str
    parser_name: Literal["markdown", "plain_text"]
    parser_version: str
    created_at: str

    def __post_init__(self) -> None:
        for name in (
            "version_id",
            "document_id",
            "source_artifact_id",
            "parser_name",
            "parser_version",
            "created_at",
        ):
            _require_non_empty(name, getattr(self, name))
        _require_sha256("source_hash", self.source_hash)
        if self.parser_name not in (PARSER_MARKDOWN, PARSER_PLAIN_TEXT):
            raise ValueError(f"unsupported parser_name: {self.parser_name}")

    @classmethod
    def create(
        cls,
        *,
        document_id: str,
        artifact: SourceArtifact,
        parser_name: Literal["markdown", "plain_text"],
        parser_version: str = PARSER_VERSION,
        created_at: str | None = None,
    ) -> "DocumentVersion":
        if artifact.document_id != document_id:
            raise ValueError("artifact document_id does not match version document_id")
        return cls(
            version_id=stable_id(
                "version",
                document_id,
                artifact.source_hash,
                parser_name,
                parser_version,
            ),
            document_id=document_id,
            source_artifact_id=artifact.artifact_id,
            source_hash=artifact.source_hash,
            parser_name=parser_name,
            parser_version=parser_version,
            created_at=created_at or utc_now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BlockLocator:
    """Exact source location for a parsed heading or paragraph."""

    source_uri: str
    start_line: int
    end_line: int
    block_index: int
    block_kind: Literal["heading", "paragraph"]
    heading_path: tuple[str, ...] = ()
    paragraph_index: int | None = None

    def __post_init__(self) -> None:
        _require_non_empty("source_uri", self.source_uri)
        if self.start_line <= 0 or self.end_line < self.start_line:
            raise ValueError("invalid line range")
        if self.block_index < 0:
            raise ValueError("block_index must be non-negative")
        if self.paragraph_index is not None and self.paragraph_index < 0:
            raise ValueError("paragraph_index must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["heading_path"] = list(self.heading_path)
        return data


@dataclass(frozen=True)
class ParsedBlock:
    """Deterministic parser output consumed by the chunker."""

    kind: Literal["heading", "paragraph"]
    text: str
    locator: BlockLocator

    def __post_init__(self) -> None:
        _require_non_empty("text", self.text)
        if self.kind != self.locator.block_kind:
            raise ValueError("block kind and locator kind must match")


@dataclass(frozen=True)
class ChunkConfig:
    """Frozen chunking behavior whose canonical form is hashed into every chunk."""

    max_chars: int = 1200
    min_chars: int = 120
    overlap_units: int = 1
    long_block_overlap_chars: int = 120
    include_heading_path: bool = True

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if self.min_chars < 0 or self.min_chars > self.max_chars:
            raise ValueError("min_chars must be between 0 and max_chars")
        if self.overlap_units < 0:
            raise ValueError("overlap_units must be non-negative")
        if not 0 <= self.long_block_overlap_chars < self.max_chars:
            raise ValueError("long_block_overlap_chars must be in [0, max_chars)")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def config_hash(self) -> str:
        return sha256_text(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class ChunkLocator:
    """Citation-ready source range for one deterministic chunk."""

    source_uri: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    start_paragraph: int
    end_paragraph: int
    start_fragment: int = 0
    end_fragment: int = 0
    overlap_from_previous: bool = False

    def __post_init__(self) -> None:
        _require_non_empty("source_uri", self.source_uri)
        if self.start_line <= 0 or self.end_line < self.start_line:
            raise ValueError("invalid chunk line range")
        if self.start_paragraph < 0 or self.end_paragraph < self.start_paragraph:
            raise ValueError("invalid paragraph range")
        if self.start_fragment < 0 or self.end_fragment < 0:
            raise ValueError("fragment indexes must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["heading_path"] = list(self.heading_path)
        return data


@dataclass(frozen=True)
class Chunk:
    """Immutable text unit stored in the registry and FTS5 table."""

    chunk_id: str
    document_id: str
    version_id: str
    ordinal: int
    text: str
    content_hash: str
    source_hash: str
    chunk_config_hash: str
    locator: ChunkLocator
    created_at: str

    def __post_init__(self) -> None:
        for name in ("chunk_id", "document_id", "version_id", "text", "created_at"):
            _require_non_empty(name, getattr(self, name))
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        _require_sha256("content_hash", self.content_hash)
        _require_sha256("source_hash", self.source_hash)
        _require_sha256("chunk_config_hash", self.chunk_config_hash)
        if self.content_hash != sha256_text(self.text):
            raise ValueError("content_hash does not match chunk text")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["locator"] = self.locator.to_dict()
        return data


@dataclass(frozen=True)
class IndexManifest:
    """Snapshot of the active registry/index contract after one mutation."""

    manifest_id: str
    schema_version: int
    index_version: str
    created_at: str
    chunk_config_hash: str
    parser_versions: tuple[str, ...]
    document_count: int
    version_count: int
    chunk_count: int
    state: Literal["ready", "building", "broken"]
    corpus_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in ("manifest_id", "index_version", "created_at", "chunk_config_hash", "corpus_hash", "content_hash"):
            _require_non_empty(name, getattr(self, name))
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        for name in ("document_count", "version_count", "chunk_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        _require_sha256("chunk_config_hash", self.chunk_config_hash)
        _require_sha256("corpus_hash", self.corpus_hash)
        _require_sha256("content_hash", self.content_hash)
        expected = self.compute_content_hash(
            schema_version=self.schema_version,
            index_version=self.index_version,
            chunk_config_hash=self.chunk_config_hash,
            parser_versions=self.parser_versions,
            document_count=self.document_count,
            version_count=self.version_count,
            chunk_count=self.chunk_count,
            state=self.state,
            corpus_hash=self.corpus_hash,
        )
        if expected != self.content_hash:
            raise ValueError("content_hash does not match manifest fields")

    @staticmethod
    def compute_content_hash(
        *,
        schema_version: int,
        index_version: str,
        chunk_config_hash: str,
        parser_versions: tuple[str, ...],
        document_count: int,
        version_count: int,
        chunk_count: int,
        state: str,
        corpus_hash: str,
    ) -> str:
        payload = {
            "schema_version": schema_version,
            "index_version": index_version,
            "chunk_config_hash": chunk_config_hash,
            "parser_versions": sorted(parser_versions),
            "document_count": document_count,
            "version_count": version_count,
            "chunk_count": chunk_count,
            "state": state,
            "corpus_hash": corpus_hash,
        }
        return sha256_text(canonical_json(payload))

    @classmethod
    def create(
        cls,
        *,
        chunk_config_hash: str,
        parser_versions: tuple[str, ...],
        document_count: int,
        version_count: int,
        chunk_count: int,
        corpus_hash: str,
        state: Literal["ready", "building", "broken"] = "ready",
        schema_version: int = INDEX_SCHEMA_VERSION,
        index_version: str = INDEX_VERSION,
        created_at: str | None = None,
    ) -> "IndexManifest":
        content_hash = cls.compute_content_hash(
            schema_version=schema_version,
            index_version=index_version,
            chunk_config_hash=chunk_config_hash,
            parser_versions=parser_versions,
            document_count=document_count,
            version_count=version_count,
            chunk_count=chunk_count,
            state=state,
            corpus_hash=corpus_hash,
        )
        return cls(
            manifest_id=stable_id("manifest", content_hash),
            schema_version=schema_version,
            index_version=index_version,
            created_at=created_at or utc_now_iso(),
            chunk_config_hash=chunk_config_hash,
            parser_versions=tuple(sorted(parser_versions)),
            document_count=document_count,
            version_count=version_count,
            chunk_count=chunk_count,
            state=state,
            corpus_hash=corpus_hash,
            content_hash=content_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["parser_versions"] = list(self.parser_versions)
        return data


@dataclass(frozen=True)
class RegistryMutationResult:
    """Deterministic add/update/delete result for the Phase A data contract."""

    operation: Literal["add", "update", "delete"]
    document_id: str
    version_id: str | None
    inserted_chunks: int
    deactivated_versions: int
    deactivated_chunks: int
    manifest_id: str

    def __post_init__(self) -> None:
        _require_non_empty("document_id", self.document_id)
        _require_non_empty("manifest_id", self.manifest_id)
        for name in ("inserted_chunks", "deactivated_versions", "deactivated_chunks"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
