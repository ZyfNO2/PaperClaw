"""Domain-independent public contracts for academic parsing and retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

ACADEMIC_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if min(self.x0, self.y0) < 0 or self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("invalid bounding box")


@dataclass(frozen=True)
class AcademicLocator:
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

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["section_path"] = list(self.section_path)
        return data


@dataclass(frozen=True)
class AcademicObject:
    object_id: str
    object_type: Literal[
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
    ]
    reading_order: int
    locator: AcademicLocator
    text: str | None = None
    asset_hash: str | None = None
    provenance: Literal["extracted", "inferred"] = "extracted"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["locator"] = self.locator.to_dict()
        return data


@dataclass(frozen=True)
class ParseResult:
    manifest_id: str
    paper_id: str
    version_id: str
    parser_name: str
    parser_version: str
    parser_fingerprint: str
    status: Literal["ready", "partial", "failed"]
    page_count: int
    objects: tuple[AcademicObject, ...]
    warnings: tuple[str, ...] = ()


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
            raise ValueError(
                "retrieval candidate and character budgets must be bounded"
            )
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

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("retrieval text must not be empty")
        allowed = {"lexical", "dense", "visual"}
        if any(channel not in allowed for channel in self.channels):
            raise ValueError("unsupported retrieval channel")

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "channels": list(self.channels),
            "paper_ids": list(self.paper_ids),
            "object_types": list(self.object_types),
            "budget": asdict(self.budget),
        }

    @classmethod
    def from_dict(cls, value):
        return cls(
            value["text"],
            tuple(value.get("channels", ("lexical", "dense", "visual"))),
            tuple(value.get("paper_ids", ())),
            tuple(value.get("object_types", ())),
            RetrievalBudget(**value.get("budget", {})),
        )


@dataclass(frozen=True)
class RetrievalCandidate:
    locator: AcademicLocator
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
    schema_version: int = ACADEMIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            self.sufficiency == "sufficient"
            and "visual" in self.trace.channels
            and "visual" in self.trace.degraded_channels
            and self.trace.channels == ("visual",)
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
    def from_dict(cls, value):
        candidates = tuple(
            RetrievalCandidate(
                _locator_from_dict(item["locator"]),
                item["text"],
                dict(item["channel_scores"]),
                item["fused_score"],
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
        )
        return cls(
            value["bundle_id"],
            value["project_id"],
            value["query"],
            candidates,
            value["sufficiency"],
            tuple(value["reasons"]),
            trace,
            value.get("schema_version", ACADEMIC_SCHEMA_VERSION),
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


def _locator_from_dict(value) -> AcademicLocator:
    bbox = BoundingBox(**value["bounding_box"]) if value.get("bounding_box") else None
    line_range = tuple(value["line_range"]) if value.get("line_range") else None
    return AcademicLocator(
        value["paper_id"],
        value["version_id"],
        value["object_id"],
        value["page_number"],
        value["object_type"],
        value["source_hash"],
        tuple(value.get("section_path", ())),
        bbox,
        value.get("paragraph_index"),
        line_range,
        value.get("table_row"),
        value.get("table_column"),
    )
