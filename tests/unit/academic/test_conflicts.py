from __future__ import annotations

from paperclaw.academic import EvidenceLocator
from paperclaw.academic.conflicts import StructuredEvidence, detect_evidence_conflicts


def _locator(version: str = "v1") -> EvidenceLocator:
    return EvidenceLocator("paper-1", version, "object-1", 1, "table_cell", "a" * 64)


def _e(evidence_id: str, **values) -> StructuredEvidence:
    return StructuredEvidence(evidence_id, "claim-1", **values)


def test_detects_structured_conflict_classes() -> None:
    findings = detect_evidence_conflicts(
        (
            _e("a", doi="10.1/a", metric="accuracy", value="90", unit="%", direction="positive", method_configuration={"lr": "1e-3"}, dataset="A", split="test", paper_version="accepted"),
            _e("b", doi="10.1/b", metric="accuracy", value="0.8", unit="ratio", direction="negative", method_configuration={"lr": "1e-4"}, dataset="B", split="train", paper_version="preprint"),
        )
    )
    assert {item.conflict_type for item in findings} == {
        "identity", "metric_value", "direction", "method_configuration",
        "dataset", "split", "paper_version",
    }
    assert all(item.evidence_ids == ("a", "b") for item in findings)
    assert all(item.recommended_corrective_strategy for item in findings)


def test_unit_conversion_and_order_are_stable() -> None:
    left = _e("a", metric="length", value="1", unit="m")
    right = _e("b", metric="length", value="1000", unit="mm")
    assert detect_evidence_conflicts((left, right, left)) == ()
    assert detect_evidence_conflicts((right, left)) == ()
    incompatible = _e("c", metric="length", value="1", unit="s")
    result = detect_evidence_conflicts((left, incompatible))
    assert [item.conflict_type for item in result] == ["unit"]


def test_missing_fields_and_unrelated_claims_are_not_conflicts() -> None:
    assert detect_evidence_conflicts((_e("a"), _e("b", metric="accuracy"))) == ()
    other = StructuredEvidence("c", "claim-2", doi="10.1/other")
    assert detect_evidence_conflicts((_e("a", doi="10.1/a"), other)) == ()


def test_superseded_locator_and_version_conflict() -> None:
    old = _e("old", locator=_locator("v1"), is_active_version=False)
    current = _e("new", locator=_locator("v2"), is_active_version=True)
    findings = detect_evidence_conflicts((current, old))
    assert {item.conflict_type for item in findings} == {"paper_version", "superseded_locator"}
    assert next(item for item in findings if item.conflict_type == "superseded_locator").locator_versions == ("paper-1:v1",)
