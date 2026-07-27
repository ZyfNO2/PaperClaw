from __future__ import annotations

import json

import pytest

from paperclaw.academic import (
    ACADEMIC_SCHEMA_VERSION,
    AcademicLocator,
    BoundingBox,
    EvidenceBundle,
    RetrievalBudget,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalTrace,
)


def test_academic_v1_contract_round_trips_complete_locator_and_bundle() -> None:
    locator = AcademicLocator(
        paper_id="paper-1",
        version_id="version-2",
        object_id="table-3-cell-2-4",
        page_number=7,
        object_type="table_cell",
        source_hash="a" * 64,
        section_path=("Experiments", "Ablation"),
        bounding_box=BoundingBox(10.0, 20.0, 30.0, 40.0),
        paragraph_index=5,
        line_range=(11, 13),
        table_row=2,
        table_column=4,
    )
    candidate = RetrievalCandidate(
        locator=locator,
        text="F1 = 91.2",
        channel_scores={"lexical": 0.8, "dense": 0.7, "visual": 0.9},
        fused_score=0.86,
        explanation=("weighted_rrf",),
        provenance="extracted",
    )
    trace = RetrievalTrace(
        trace_id="trace-1",
        request_fingerprint="b" * 64,
        index_generation_id="generation-1",
        channels=("lexical", "dense", "visual"),
        model_fingerprints={"visual": "colqwen2:test"},
        rounds_used={"primary": 1, "corrective": 0, "conflict": 0},
        degraded_channels=(),
        stop_reason="sufficient",
    )
    bundle = EvidenceBundle(
        bundle_id="bundle-1",
        project_id="project-1",
        query="What is the F1 value in Table 3?",
        candidates=(candidate,),
        sufficiency="sufficient",
        reasons=("grounded table cell found",),
        trace=trace,
    )

    encoded = json.dumps(bundle.to_dict(), ensure_ascii=False, sort_keys=True)
    restored = EvidenceBundle.from_dict(json.loads(encoded))

    assert restored == bundle
    assert restored.schema_version == ACADEMIC_SCHEMA_VERSION
    assert restored.candidates[0].locator.table_row == 2
    assert restored.candidates[0].locator.table_column == 4


def test_retrieval_request_validates_channels_and_bounded_rounds() -> None:
    request = RetrievalRequest(
        text="Compare the architecture figures",
        channels=("visual", "lexical"),
        object_types=("figure", "caption"),
        budget=RetrievalBudget(
            max_candidates=8,
            max_chars=8_000,
            max_primary_rounds=1,
            max_corrective_rounds=1,
            max_conflict_rounds=1,
        ),
    )

    assert RetrievalRequest.from_dict(request.to_dict()) == request

    with pytest.raises(ValueError, match="unsupported retrieval channel"):
        RetrievalRequest(text="query", channels=("unbounded_web",))

    with pytest.raises(ValueError, match="primary"):
        RetrievalBudget(max_primary_rounds=2)


def test_visual_request_cannot_be_sufficient_when_visual_channel_is_degraded() -> None:
    trace = RetrievalTrace(
        trace_id="trace-visual",
        request_fingerprint="c" * 64,
        index_generation_id="generation-1",
        channels=("visual",),
        model_fingerprints={},
        rounds_used={"primary": 1, "corrective": 0, "conflict": 0},
        degraded_channels=("visual",),
        stop_reason="visual_unavailable",
    )

    with pytest.raises(ValueError, match="degraded visual"):
        EvidenceBundle(
            bundle_id="bundle-visual",
            project_id="project-1",
            query="Where is the attention module in the figure?",
            candidates=(),
            sufficiency="sufficient",
            reasons=("incorrect",),
            trace=trace,
        )
