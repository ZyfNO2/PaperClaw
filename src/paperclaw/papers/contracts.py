"""Stable public contracts for project-scoped academic paper ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class MetadataValue:
    value: str | int | tuple[str, ...] | None = None
    source: str = "unknown"
    status: str = "candidate"

    def __post_init__(self) -> None:
        if self.status not in {"candidate", "confirmed"}:
            raise ValueError("metadata status must be candidate or confirmed")

    def to_dict(self) -> dict[str, object]:
        value: object = list(self.value) if isinstance(self.value, tuple) else self.value
        return {"value": value, "source": self.source, "status": self.status}


@dataclass(frozen=True)
class PaperMetadata:
    title: MetadataValue = field(default_factory=MetadataValue)
    authors: MetadataValue = field(default_factory=MetadataValue)
    year: MetadataValue = field(default_factory=MetadataValue)
    doi: MetadataValue = field(default_factory=MetadataValue)
    arxiv_id: MetadataValue = field(default_factory=MetadataValue)
    language: MetadataValue = field(default_factory=MetadataValue)

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name).to_dict() for name in _METADATA_FIELDS}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PaperMetadata":
        items = {}
        for name in _METADATA_FIELDS:
            raw = value.get(name, {})
            if not isinstance(raw, Mapping):
                raise ValueError("invalid persisted paper metadata")
            item = raw.get("value")
            if name == "authors" and isinstance(item, list):
                item = tuple(str(part) for part in item)
            items[name] = MetadataValue(
                item, str(raw.get("source", "unknown")), str(raw.get("status", "candidate"))
            )
        return cls(**items)


@dataclass(frozen=True)
class MetadataPatch:
    title: str | None = None
    authors: tuple[str, ...] | None = None
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    language: str | None = None


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    project_id: str
    current_version_id: str
    current_version_number: int
    metadata: PaperMetadata
    metadata_revision: int
    created_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "paper_id": self.paper_id,
            "project_id": self.project_id,
            "current_version_id": self.current_version_id,
            "current_version_number": self.current_version_number,
            "metadata": self.metadata.to_dict(),
            "metadata_revision": self.metadata_revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PaperVersion:
    version_id: str
    paper_id: str
    version_number: int
    format: str
    original_filename: str
    byte_length: int
    sha256: str
    managed_locator: str
    source_path: str
    created_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "version_id": self.version_id,
            "paper_id": self.paper_id,
            "version_number": self.version_number,
            "format": self.format,
            "original_filename": self.original_filename,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "source": {"kind": "local_import", "filename": self.original_filename},
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PaperImportRequest:
    project_id: str
    source_path: str | Path
    paper_id: str | None = None
    metadata: MetadataPatch | None = None


@dataclass(frozen=True)
class PaperImportResult:
    paper: PaperRecord
    version: PaperVersion
    created: bool
    warnings: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, object]:
        return {
            "paper": self.paper.to_public_dict(),
            "version": self.version.to_public_dict(),
            "created": self.created,
            "warnings": list(self.warnings),
        }


_METADATA_FIELDS = ("title", "authors", "year", "doi", "arxiv_id", "language")

