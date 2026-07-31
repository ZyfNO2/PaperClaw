"""Deterministic conflict detection over normalized academic evidence.

This module deliberately accepts structured fields only.  Retrieval stop reasons,
prompts, prose keywords, and model judgements are not conflict signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Literal, Mapping, cast

from .contracts import EvidenceLocator

ConflictType = Literal[
    "identity",
    "metric_value",
    "unit",
    "direction",
    "method_configuration",
    "dataset",
    "split",
    "paper_version",
    "superseded_locator",
]


@dataclass(frozen=True)
class StructuredEvidence:
    """Normalized facts extracted upstream; absent fields mean unknown, not conflict."""

    evidence_id: str
    claim_key: str
    locator: EvidenceLocator | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    canonical_title: str | None = None
    metric: str | None = None
    value: str | int | float | Decimal | None = None
    unit: str | None = None
    direction: Literal["positive", "negative", "neutral"] | None = None
    method_configuration: Mapping[str, str] = field(default_factory=dict)
    dataset: str | None = None
    split: str | None = None
    paper_version: str | None = None
    is_active_version: bool | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.claim_key:
            raise ValueError("evidence_id and claim_key must not be empty")


@dataclass(frozen=True)
class EvidenceConflict:
    conflict_type: ConflictType
    evidence_ids: tuple[str, ...]
    locator_versions: tuple[str, ...]
    reason: str
    severity: Literal["warning", "error"]
    recommended_corrective_strategy: str


_UNIT_SCALE: dict[str, tuple[str, Decimal]] = {
    "%": ("ratio", Decimal("0.01")),
    "percent": ("ratio", Decimal("0.01")),
    "ratio": ("ratio", Decimal("1")),
    "m": ("length", Decimal("1")),
    "cm": ("length", Decimal("0.01")),
    "mm": ("length", Decimal("0.001")),
    "s": ("time", Decimal("1")),
    "ms": ("time", Decimal("0.001")),
}


def _norm(value: str | None) -> str | None:
    return " ".join(value.casefold().split()) if value else None


def _number(value: str | int | float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _versions(*items: StructuredEvidence) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                f"{item.locator.paper_id}:{item.locator.version_id}"
                for item in items
                if item.locator is not None
            }
        )
    )


def _conflict(
    kind: ConflictType,
    left: StructuredEvidence,
    right: StructuredEvidence,
    reason: str,
    strategy: str,
    *,
    severity: Literal["warning", "error"] = "error",
) -> EvidenceConflict:
    return EvidenceConflict(
        kind,
        tuple(sorted((left.evidence_id, right.evidence_id))),
        _versions(left, right),
        reason,
        severity,
        strategy,
    )


def detect_evidence_conflicts(
    evidence: tuple[StructuredEvidence, ...],
) -> tuple[EvidenceConflict, ...]:
    """Return stable conflicts; duplicate evidence and missing facts are ignored."""

    unique = {item.evidence_id: item for item in evidence}
    findings: set[EvidenceConflict] = set()
    for left, right in combinations(sorted(unique.values(), key=lambda x: x.evidence_id), 2):
        if left.claim_key != right.claim_key:
            continue
        identities = (
            ("doi", _norm(left.doi), _norm(right.doi)),
            ("arXiv", _norm(left.arxiv_id), _norm(right.arxiv_id)),
            ("title", _norm(left.canonical_title), _norm(right.canonical_title)),
        )
        for label, a, b in identities:
            if a is not None and b is not None and a != b:
                findings.add(_conflict("identity", left, right, f"{label} identities differ", "exact_identity_lookup"))

        same_metric = _norm(left.metric) is not None and _norm(left.metric) == _norm(right.metric)
        lv, rv = _number(left.value), _number(right.value)
        lu, ru = _norm(left.unit), _norm(right.unit)
        if same_metric and lv is not None and rv is not None:
            if lu and ru and lu in _UNIT_SCALE and ru in _UNIT_SCALE:
                ldim, lscale = _UNIT_SCALE[lu]
                rdim, rscale = _UNIT_SCALE[ru]
                if ldim != rdim:
                    findings.add(_conflict("unit", left, right, "metric units are not convertible", "retrieve_metric_definition"))
                elif lv * lscale != rv * rscale:
                    findings.add(_conflict("metric_value", left, right, "normalized metric values differ", "retrieve_same_metric_and_split"))
            elif lu and ru and lu != ru:
                findings.add(_conflict("unit", left, right, "metric units are unknown or not convertible", "retrieve_metric_definition"))
            elif lu == ru and lv != rv:
                findings.add(_conflict("metric_value", left, right, "metric values differ", "retrieve_same_metric_and_split"))

        if left.direction and right.direction and left.direction != right.direction:
            findings.add(_conflict("direction", left, right, "conclusion directions differ", "retrieve_conclusion_context"))
        if left.method_configuration and right.method_configuration and dict(left.method_configuration) != dict(right.method_configuration):
            findings.add(_conflict("method_configuration", left, right, "method configurations differ", "retrieve_method_configuration"))
        for kind, a, b, strategy in (
            ("dataset", _norm(left.dataset), _norm(right.dataset), "filter_same_dataset"),
            ("split", _norm(left.split), _norm(right.split), "filter_same_dataset_split"),
            ("paper_version", _norm(left.paper_version), _norm(right.paper_version), "retrieve_active_paper_version"),
        ):
            if a is not None and b is not None and a != b:
                findings.add(
                    _conflict(
                        cast(ConflictType, kind),
                        left,
                        right,
                        f"{kind.replace('_', ' ')} values differ",
                        strategy,
                    )
                )
        if left.locator and right.locator and left.locator.paper_id == right.locator.paper_id and left.locator.version_id != right.locator.version_id:
            findings.add(_conflict("paper_version", left, right, "locators target different paper versions", "retrieve_active_paper_version"))

    for item in unique.values():
        if item.locator is not None and item.is_active_version is False:
            findings.add(
                EvidenceConflict(
                    "superseded_locator",
                    (item.evidence_id,),
                    _versions(item),
                    "locator targets a non-active paper version",
                    "error",
                    "resolve_and_retrieve_active_version",
                )
            )
    return tuple(sorted(findings, key=lambda x: (x.conflict_type, x.evidence_ids, x.reason)))
