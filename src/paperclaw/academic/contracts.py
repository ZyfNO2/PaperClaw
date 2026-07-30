"""Canonical ``academic.v1`` contracts shared by PaperClaw and PaperAgent.

PaperClaw owns this wire interface.  Runtime-specific and third-party parser
types must be converted here before crossing a process or repository seam.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import re
from typing import Any, Literal, Mapping

ACADEMIC_SCHEMA_VERSION = "academic.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_sha256(value: str, name: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")


def _require_schema(value: str) -> None:
    if value != ACADEMIC_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported academic schema {value!r}; expected {ACADEMIC_SCHEMA_VERSION!r}"
        )


@dataclass(frozen=True)
class BoundingBox:
    """PDF point coordinates, top-left origin, on a one-based page."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if min(self.x0, self.y0) < 0 or self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("invalid bounding box")


@dataclass(frozen=True)
class EvidenceLocator:
    """Stable, replayable identity for one object in one immutable paper version."""

    paper_id: str
    version_id: str
    object_id: str
    page_number: int
    object_type: str
    source_hash: str
    section_path: tuple[str, ...] = ()
    bounding_box: BoundingBox | None = None
    paragraph_index: int | None = None
    line_range: tuple[int, int] | None = None
    table_row: int | None = None
    table_column: int | None = None
    schema_version: str = ACADEMIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version)
        _require_sha256(self.source_hash, "source_hash")
        if not all((self.paper_id, self.version_id, self.object_id, self.object_type)):
            raise ValueError("locator identity fields must not be empty")
        if self.page_number < 1:
            raise ValueError("page_number must be one-based")
        if self.paragraph_index is not None and self.paragraph_index < 0:
            raise ValueError("paragraph_index must be non-negative")
        if self.line_range is not None:
            start, end = self.line_range
            if start < 0 or end < start:
                raise ValueError("invalid line_range")
        if (self.table_row is None) != (self.table_column is None):
            raise ValueError("table coordinates must include both row and column")
        if self.table_row is not None and min(self.table_row, self.table_column or 0) < 0:
            raise ValueError("table coordinates must be non-negative")

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["section_path"] = list(self.section_path)
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceLocator:
        _require_schema(str(value.get("schema_version", "")))
        bbox = BoundingBox(**value["bounding_box"]) if value.get("bounding_box") else None
        line_range = tuple(value["line_range"]) if value.get("line_range") else None
        return cls(
            paper_id=str(value["paper_id"]),
            version_id=str(value["version_id"]),
            object_id=str(value["object_id"]),
            page_number=int(value["page_number"]),
            object_type=str(value["object_type"]),
            source_hash=str(value["source_hash"]),
            section_path=tuple(value.get("section_path", ())),
            bounding_box=bbox,
            paragraph_index=value.get("paragraph_index"),
            line_range=line_range,
            table_row=value.get("table_row"),
            table_column=value.get("table_column"),
            schema_version=str(value["schema_version"]),
        )


# One-release source compatibility only.  Wire payloads and documentation use
# EvidenceLocator exclusively.
AcademicLocator = EvidenceLocator


@dataclass(frozen=True)
class AssetReference:
    asset_hash: str
    kind: Literal["page", "region"]
    media_type: Literal["image/png"] = "image/png"
    width_px: int | None = None
    height_px: int | None = None
    dpi: int = 120

    def __post_init__(self) -> None:
        _require_sha256(self.asset_hash, "asset_hash")
        if self.width_px is not None and self.width_px < 1:
            raise ValueError("width_px must be positive")
        if self.height_px is not None and self.height_px < 1:
            raise ValueError("height_px must be positive")
        if self.dpi < 72 or self.dpi > 600:
            raise ValueError("dpi must be in [72, 600]")


@dataclass(frozen=True)
class PaperVersion:
    version_id: str
    version_number: int
    source_hash: str
    format: str
    original_filename: str
    byte_length: int
    created_at: str

    def __post_init__(self) -> None:
        _require_sha256(self.source_hash, "source_hash")
        if self.version_number < 1 or self.byte_length < 0:
            raise ValueError("invalid paper version")


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    project_id: str
    current_version: PaperVersion
    metadata: Mapping[str, Any]
    metadata_revision: int
    created_at: str
    updated_at: str
    source: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ACADEMIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version)
        if not self.paper_id or not self.project_id or self.metadata_revision < 1:
            raise ValueError("invalid paper record identity")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "paper_id": self.paper_id,
            "project_id": self.project_id,
            "current_version": asdict(self.current_version),
            "metadata": dict(self.metadata),
            "metadata_revision": self.metadata_revision,
            "source": dict(self.source),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PaperRecord:
        _require_schema(str(value.get("schema_version", "")))
        return cls(
            paper_id=str(value["paper_id"]),
            project_id=str(value["project_id"]),
            current_version=PaperVersion(**value["current_version"]),
            metadata=dict(value["metadata"]),
            metadata_revision=int(value["metadata_revision"]),
            source=dict(value.get("source", {})),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            schema_version=str(value["schema_version"]),
        )


AcademicObjectType = Literal[
    "document",
    "page",
    "section",
    "paragraph",
    "figure",
    "caption",
    "table",
    "table_cell",
    "equation",
    "algorithm",
    "reference",
    "citation",
    "repository_link",
]


@dataclass(frozen=True)
class AcademicObject:
    object_id: str
    object_type: AcademicObjectType
    reading_order: int
    locator: EvidenceLocator
    text: str | None = None
    assets: tuple[AssetReference, ...] = ()
    structured_content: Mapping[str, Any] = field(default_factory=dict)
    provenance: Literal["extracted", "inferred"] = "extracted"
    schema_version: str = ACADEMIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version)
        if self.object_id != self.locator.object_id:
            raise ValueError("object and locator identity mismatch")
        if self.object_type != self.locator.object_type:
            raise ValueError("object and locator type mismatch")
        if self.reading_order < 0:
            raise ValueError("reading_order must be non-negative")
        if (
            self.locator.bounding_box is None
            and self.object_type not in {"document"}
            and self.provenance == "extracted"
        ):
            object.__setattr__(self, "provenance", "inferred")

    @property
    def asset_hash(self) -> str | None:
        """Compatibility view for callers written before academic.v1 freeze."""

        for asset in self.assets:
            if asset.kind == "region":
                return asset.asset_hash
        return self.assets[0].asset_hash if self.assets else None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_id": self.object_id,
            "object_type": self.object_type,
            "reading_order": self.reading_order,
            "locator": self.locator.to_dict(),
            "text": self.text,
            "assets": [asdict(asset) for asset in self.assets],
            "structured_content": dict(self.structured_content),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AcademicObject:
        _require_schema(str(value.get("schema_version", "")))
        assets = tuple(AssetReference(**item) for item in value.get("assets", ()))
        return cls(
            object_id=str(value["object_id"]),
            object_type=value["object_type"],
            reading_order=int(value["reading_order"]),
            locator=EvidenceLocator.from_dict(value["locator"]),
            text=value.get("text"),
            assets=assets,
            structured_content=dict(value.get("structured_content", {})),
            provenance=value.get("provenance", "extracted"),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True)
class ParseResult:
    manifest_id: str
    paper_id: str
    version_id: str
    source_hash: str
    parser_name: str
    parser_version: str
    parser_fingerprint: str
    status: Literal["staging", "ready", "partial", "failed", "stale"]
    page_count: int
    objects: tuple[AcademicObject, ...]
    warnings: tuple[str, ...] = ()
    schema_version: str = ACADEMIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version)
        _require_sha256(self.source_hash, "source_hash")
        if self.status == "ready" and self.warnings:
            raise ValueError("ready parse manifests cannot contain warnings")
        if self.status == "failed" and self.objects:
            raise ValueError("failed parse manifests cannot expose objects")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "paper_id": self.paper_id,
            "version_id": self.version_id,
            "source_hash": self.source_hash,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "parser_fingerprint": self.parser_fingerprint,
            "status": self.status,
            "page_count": self.page_count,
            "objects": [item.to_dict() for item in self.objects],
            "warnings": list(self.warnings),
        }

    def to_public_summary(self) -> dict[str, object]:
        """Stable parse envelope shared by REST, CLI and desktop adapters."""

        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "status": self.status,
            "paper_id": self.paper_id,
            "version_id": self.version_id,
            "source_hash": self.source_hash,
            "page_count": self.page_count,
            "object_count": len(self.objects),
            "object_types": sorted({item.object_type for item in self.objects}),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class IndexGeneration:
    generation_id: str
    corpus_hash: str
    model_fingerprint: str
    state: Literal["building", "ready", "failed"]
    object_count: int


@dataclass(frozen=True)
class AcademicQuery:
    text: str
    paper_ids: tuple[str, ...] = ()
    object_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalBudget:
    max_candidates: int = 10
    max_chars: int = 12_000
    max_primary_rounds: int = 1
    max_corrective_rounds: int = 1
    max_conflict_rounds: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.max_candidates <= 100 or self.max_chars < 1:
            raise ValueError("retrieval candidate and character budgets must be bounded")
        if self.max_primary_rounds != 1:
            raise ValueError("primary retrieval rounds must equal 1")
        if not 0 <= self.max_corrective_rounds <= 1:
            raise ValueError("corrective retrieval rounds must be in [0, 1]")
        if not 0 <= self.max_conflict_rounds <= 1:
            raise ValueError("conflict retrieval rounds must be in [0, 1]")


@dataclass(frozen=True)
class RetrievalRequest:
    text: str
    channels: tuple[str, ...] = ("lexical", "dense", "visual")
    paper_ids: tuple[str, ...] = ()
    object_types: tuple[str, ...] = ()
    budget: RetrievalBudget = field(default_factory=RetrievalBudget)
    version_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("retrieval text must not be empty")
        allowed = {"exact", "lexical", "dense", "visual"}
        if any(channel not in allowed for channel in self.channels):
            raise ValueError("unsupported retrieval channel")

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "channels": list(self.channels),
            "paper_ids": list(self.paper_ids),
            "version_ids": list(self.version_ids),
            "object_types": list(self.object_types),
            "budget": asdict(self.budget),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RetrievalRequest:
        return cls(
            str(value["text"]),
            tuple(value.get("channels", ("lexical", "dense", "visual"))),
            tuple(value.get("paper_ids", ())),
            tuple(value.get("object_types", ())),
            RetrievalBudget(**value.get("budget", {})),
            tuple(value.get("version_ids", ())),
        )


@dataclass(frozen=True)
class RetrievalCandidate:
    locator: EvidenceLocator
    text: str
    channel_scores: dict[str, float]
    fused_score: float
    explanation: tuple[str, ...]
    provenance: Literal["extracted", "inferred"] = "extracted"

    @property
    def lexical_score(self) -> float:
        return self.channel_scores.get("lexical", 0.0)

    @property
    def dense_score(self) -> float:
        return self.channel_scores.get("dense", 0.0)

    @property
    def visual_score(self) -> float:
        return self.channel_scores.get("visual", 0.0)

    def to_dict(self) -> dict[str, object]:
        return {
            "locator": self.locator.to_dict(),
            "text": self.text,
            "channel_scores": dict(self.channel_scores),
            "fused_score": self.fused_score,
            "explanation": list(self.explanation),
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class RetrievalTrace:
    trace_id: str
    request_fingerprint: str
    index_generation_id: str
    channels: tuple[str, ...]
    model_fingerprints: dict[str, str]
    rounds_used: dict[str, int]
    degraded_channels: tuple[str, ...]
    stop_reason: str
    corrective_details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["channels"] = list(self.channels)
        data["degraded_channels"] = list(self.degraded_channels)
        return data


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    project_id: str
    query: str
    candidates: tuple[RetrievalCandidate, ...]
    sufficiency: Literal["sufficient", "partial", "insufficient"]
    reasons: tuple[str, ...]
    trace: RetrievalTrace
    schema_version: str = ACADEMIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version)
        if (
            self.sufficiency == "sufficient"
            and self.trace.channels == ("visual",)
            and "visual" in self.trace.degraded_channels
        ):
            raise ValueError("degraded visual-only retrieval cannot be sufficient")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "project_id": self.project_id,
            "query": self.query,
            "candidates": [item.to_dict() for item in self.candidates],
            "sufficiency": self.sufficiency,
            "reasons": list(self.reasons),
            "trace": self.trace.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceBundle:
        _require_schema(str(value.get("schema_version", "")))
        candidates = tuple(
            RetrievalCandidate(
                EvidenceLocator.from_dict(item["locator"]),
                str(item["text"]),
                dict(item["channel_scores"]),
                float(item["fused_score"]),
                tuple(item["explanation"]),
                item.get("provenance", "extracted"),
            )
            for item in value["candidates"]
        )
        raw = value["trace"]
        trace = RetrievalTrace(
            raw["trace_id"],
            raw["request_fingerprint"],
            raw["index_generation_id"],
            tuple(raw["channels"]),
            dict(raw["model_fingerprints"]),
            dict(raw["rounds_used"]),
            tuple(raw["degraded_channels"]),
            raw["stop_reason"],
            dict(raw.get("corrective_details", {})),
        )
        return cls(
            str(value["bundle_id"]),
            str(value["project_id"]),
            str(value["query"]),
            candidates,
            value["sufficiency"],
            tuple(value["reasons"]),
            trace,
            str(value["schema_version"]),
        )


@dataclass(frozen=True)
class MemoryEntrySnapshot:
    entry_id: str
    scope: Literal["user", "project", "task"]
    category: str
    content: str
    content_hash: str
    updated_at: str


@dataclass(frozen=True)
class MemorySnapshot:
    project_id: str
    entries: tuple[MemoryEntrySnapshot, ...]
    used_chars: Mapping[str, int]
    limit_chars: Mapping[str, int]
    fingerprint: str
    generated_at: str
    schema_version: str = ACADEMIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version)
        _require_sha256(self.fingerprint, "fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "entries": [asdict(item) for item in self.entries],
            "used_chars": dict(self.used_chars),
            "limit_chars": dict(self.limit_chars),
            "fingerprint": self.fingerprint,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MemorySnapshot:
        _require_schema(str(value.get("schema_version", "")))
        return cls(
            project_id=str(value["project_id"]),
            entries=tuple(MemoryEntrySnapshot(**item) for item in value["entries"]),
            used_chars=dict(value["used_chars"]),
            limit_chars=dict(value["limit_chars"]),
            fingerprint=str(value["fingerprint"]),
            generated_at=str(value["generated_at"]),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True)
class ArtifactRevision:
    artifact_id: str
    revision_id: str
    revision_number: int
    parent_revision_id: str | None
    state: Literal["draft", "approved", "rejected", "final"]
    content_hash: str
    byte_length: int
    media_type: str
    evidence: tuple[EvidenceLocator, ...]
    created_at: str
    schema_version: str = ACADEMIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema(self.schema_version)
        _require_sha256(self.content_hash, "content_hash")
        if self.revision_number < 1 or self.byte_length < 0:
            raise ValueError("invalid artifact revision")
        if self.revision_number == 1 and self.parent_revision_id is not None:
            raise ValueError("first revision cannot have a parent")
        if self.revision_number > 1 and self.parent_revision_id is None:
            raise ValueError("later revisions require a parent")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "revision_id": self.revision_id,
            "revision_number": self.revision_number,
            "parent_revision_id": self.parent_revision_id,
            "state": self.state,
            "content_hash": self.content_hash,
            "byte_length": self.byte_length,
            "media_type": self.media_type,
            "evidence": [item.to_dict() for item in self.evidence],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArtifactRevision:
        _require_schema(str(value.get("schema_version", "")))
        return cls(
            artifact_id=str(value["artifact_id"]),
            revision_id=str(value["revision_id"]),
            revision_number=int(value["revision_number"]),
            parent_revision_id=value.get("parent_revision_id"),
            state=value["state"],
            content_hash=str(value["content_hash"]),
            byte_length=int(value["byte_length"]),
            media_type=str(value["media_type"]),
            evidence=tuple(EvidenceLocator.from_dict(item) for item in value["evidence"]),
            created_at=str(value["created_at"]),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    candidates: tuple[RetrievalCandidate, ...]
    sufficiency: Literal["sufficient", "partial", "insufficient"]
    reasons: tuple[str, ...]
    trace: RetrievalTrace | None = None

    @property
    def should_abstain(self) -> bool:
        return self.sufficiency == "insufficient"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "ACADEMIC_SCHEMA_VERSION",
    "AcademicLocator",
    "AcademicObject",
    "AcademicObjectType",
    "AcademicQuery",
    "ArtifactRevision",
    "AssetReference",
    "BoundingBox",
    "EvidenceBundle",
    "EvidenceLocator",
    "IndexGeneration",
    "MemoryEntrySnapshot",
    "MemorySnapshot",
    "PaperRecord",
    "PaperVersion",
    "ParseResult",
    "RetrievalBudget",
    "RetrievalCandidate",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalTrace",
    "utc_now",
]
