"""Domain-independent public contracts for academic parsing and retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


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

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["section_path"] = list(self.section_path)
        return data


@dataclass(frozen=True)
class AcademicObject:
    object_id: str
    object_type: Literal[
        "document", "page", "section", "paragraph", "figure", "caption",
        "table", "table_cell", "equation", "algorithm", "reference", "citation"
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


@dataclass(frozen=True)
class RetrievalCandidate:
    locator: AcademicLocator
    text: str
    lexical_score: float
    dense_score: float
    visual_score: float
    fused_score: float
    explanation: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    candidates: tuple[RetrievalCandidate, ...]
    sufficiency: Literal["sufficient", "partial", "insufficient"]
    reasons: tuple[str, ...]

    @property
    def should_abstain(self) -> bool:
        return self.sufficiency == "insufficient"

