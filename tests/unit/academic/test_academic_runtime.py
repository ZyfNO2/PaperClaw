from __future__ import annotations

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from paperclaw.academic import (  # noqa: E402
    AcademicQuery,
    AcademicRuntime,
    BoundingBox,
    RetrievalBudget,
    RetrievalRequest,
)
from paperclaw.papers import PaperImportRequest, PaperService  # noqa: E402
from paperclaw.projects import ProjectManifestStore  # noqa: E402
from paperclaw.academic.runtime import _safe_bbox  # noqa: E402


class _FakeVisualEncoder:
    fingerprint = "fake-colqwen-revision"

    def encode_images(self, paths):
        return [[[1.0, 0.0]] for _ in paths]

    def encode_query(self, query):
        return [[1.0, 0.0]]


class _SecondFakeVisualEncoder(_FakeVisualEncoder):
    fingerprint = "second-fake-colqwen-revision"


def _runtime(tmp_path: Path, *, visual_encoder=None) -> tuple[AcademicRuntime, str]:
    manifest = ProjectManifestStore(tmp_path).initialize("Academic")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "1 Introduction", fontsize=18)
    page.insert_text((72, 110), "Concrete crack evidence appears on this page.")
    page.insert_text((72, 130), "DOI 10.1234/ABC.Def")
    page.draw_rect(fitz.Rect(72, 150, 240, 230))
    source = tmp_path / "paper.pdf"
    document.save(source)
    document.close()
    papers = PaperService.for_workspace(tmp_path, project_id=manifest.project_id)
    imported = papers.import_paper(PaperImportRequest(manifest.project_id, source))
    return (
        AcademicRuntime.for_workspace(
            tmp_path, manifest.project_id, visual_encoder=visual_encoder
        ),
        imported.paper.paper_id,
    )


def test_parse_index_retrieve_resolve_and_evidence_bundle(tmp_path: Path) -> None:
    runtime, paper_id = _runtime(tmp_path)
    parsed = runtime.parse_paper(paper_id)
    assert parsed.status == "ready"
    assert parsed.page_count == 1
    assert {"document", "page", "section", "paragraph", "figure"} <= {
        item.object_type for item in parsed.objects
    }
    assert all(item.locator.version_id == parsed.version_id for item in parsed.objects)

    indexed = runtime.build_index()
    assert indexed.state == "ready"
    result = runtime.retrieve(
        AcademicQuery("crack evidence"),
        budget=RetrievalBudget(max_candidates=5),
    )
    assert result.sufficiency in {"sufficient", "partial"}
    assert result.candidates[0].locator.paper_id == paper_id
    resolved = runtime.resolve(result.candidates[0].locator)
    assert "crack" in (resolved.text or "").lower()
    expanded = runtime.expand(result.candidates[0], neighbors=1)
    assert expanded
    artifact = runtime.save_evidence_bundle(result)
    assert artifact["artifact_type"] == "evidence_bundle"
    assert ".paperclaw" not in str(artifact)
    assert (
        runtime.save_research_artifact("baseline_card", "Baseline", {"method": "BM25"})[
            "artifact_type"
        ]
        == "baseline_card"
    )
    runtime.remember("project", "Use page-level evidence for figure questions.")
    assert "page-level evidence" in runtime.memory_snapshot()["project"][0]


def test_page_and_region_assets_are_content_addressed_and_resolvable(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _runtime(tmp_path)
    parsed = runtime.parse_paper(paper_id)
    page = next(item for item in parsed.objects if item.object_type == "page")
    figure = next(item for item in parsed.objects if item.object_type == "figure")

    assert [asset.kind for asset in page.assets] == ["page"]
    assert {asset.kind for asset in figure.assets} == {"page", "region"}
    assert all(asset.width_px and asset.height_px for asset in figure.assets)
    assert runtime.resolve(figure.locator) == figure
    for asset in figure.assets:
        assert runtime.object_store.asset_path(asset.asset_hash).is_file()


def test_parser_revision_and_index_generation_are_idempotent(tmp_path: Path) -> None:
    runtime, paper_id = _runtime(tmp_path)
    first = runtime.parse_paper(paper_id)
    second = runtime.parse_paper(paper_id)
    assert second.manifest_id == first.manifest_id
    first_index = runtime.build_index()
    second_index = runtime.build_index()
    assert second_index.generation_id == first_index.generation_id


def test_insufficient_query_abstains(tmp_path: Path) -> None:
    runtime, paper_id = _runtime(tmp_path)
    runtime.parse_paper(paper_id)
    runtime.build_index()
    result = runtime.retrieve(AcademicQuery("quantum banana unobtainium"))
    assert result.sufficiency == "insufficient"
    assert result.should_abstain is True
    assert result.trace is not None
    details = result.trace.corrective_details
    assert details["primary_reason"] == "no_candidates"
    assert details["original_query"] == "quantum banana unobtainium"
    assert details["rewritten_query"] != details["original_query"]
    assert result.trace.rounds_used["corrective"] == 1


def test_exact_identifier_channel_preserves_doi_identity(tmp_path: Path) -> None:
    runtime, paper_id = _runtime(tmp_path)
    runtime.parse_paper(paper_id)
    runtime.build_index()

    result = runtime.retrieve(
        RetrievalRequest(
            "Find DOI 10.1234/ABC.Def",
            ("exact", "lexical"),
            (paper_id,),
        )
    )

    assert result.candidates
    assert result.candidates[0].channel_scores["exact"] == 1.0


def test_parser_clamps_out_of_page_and_reversed_bounding_boxes() -> None:
    bbox = _safe_bbox((900.0, -5.0, -10.0, 700.0), 600.0, 500.0)

    assert bbox == BoundingBox(0.0, 0.0, 600.0, 500.0)


def test_visual_generation_and_retrieval_use_replaceable_encoder(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _runtime(tmp_path, visual_encoder=_FakeVisualEncoder())
    runtime.parse_paper(paper_id)
    generation = runtime.build_index()
    assert "fake-colqwen-revision" in generation.model_fingerprint

    result = runtime.retrieve(AcademicQuery("diagram"))
    visual = next(
        candidate
        for candidate in result.candidates
        if candidate.channel_scores["visual"] > 0
    )
    assert visual.locator.paper_id == paper_id
    assert visual.locator.object_type in {"page", "figure"}


def test_existing_generation_is_reactivated_after_model_switch(tmp_path: Path) -> None:
    runtime_a, paper_id = _runtime(tmp_path, visual_encoder=_FakeVisualEncoder())
    runtime_a.parse_paper(paper_id)
    generation_a = runtime_a.build_index()
    runtime_b = AcademicRuntime.for_workspace(
        tmp_path, runtime_a.project_id, visual_encoder=_SecondFakeVisualEncoder()
    )
    assert runtime_b.build_index().generation_id != generation_a.generation_id

    runtime_a.build_index()
    result = runtime_a.retrieve(RetrievalRequest("diagram", ("visual",)))
    assert result.trace is not None
    assert result.trace.index_generation_id == generation_a.generation_id


def test_visual_only_request_abstains_when_channel_is_unavailable(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _runtime(tmp_path)
    runtime.parse_paper(paper_id)
    runtime.build_index()
    result = runtime.retrieve(RetrievalRequest("diagram", ("visual",)))
    assert result.should_abstain
    assert result.trace is not None
    assert result.trace.degraded_channels == ("visual",)
    assert result.trace.corrective_details["primary_reason"] == "channel_unavailable"
    assert result.trace.corrective_details["channel_changes"]["after"] == ["lexical"]


def test_retrieval_rejects_encoder_fingerprint_mismatch(tmp_path: Path) -> None:
    runtime_a, paper_id = _runtime(tmp_path, visual_encoder=_FakeVisualEncoder())
    runtime_a.parse_paper(paper_id)
    runtime_a.build_index()
    runtime_b = AcademicRuntime.for_workspace(
        tmp_path, runtime_a.project_id, visual_encoder=_SecondFakeVisualEncoder()
    )
    with pytest.raises(RuntimeError, match="model fingerprint is incompatible"):
        runtime_b.retrieve(RetrievalRequest("diagram", ("visual",)))


def test_runtime_executes_conflict_driven_corrective_round(tmp_path: Path) -> None:
    manifest = ProjectManifestStore(tmp_path).initialize("Conflict")
    papers = PaperService.for_workspace(tmp_path, project_id=manifest.project_id)
    for name, text in (
        ("paper-a.txt", "Results\nF1 is 91.2 percent dataset: Crack500 split: test"),
        ("paper-b.txt", "Results\nF1 is 88.0 percent dataset: Crack500 split: test"),
    ):
        source = tmp_path / name
        source.write_text(text, encoding="utf-8")
        papers.import_paper(PaperImportRequest(manifest.project_id, source))
    runtime = AcademicRuntime.for_workspace(tmp_path, manifest.project_id)
    for paper in papers.list_papers(manifest.project_id):
        runtime.parse_paper(paper.paper_id)
    runtime.build_index()

    result = runtime.retrieve(
        RetrievalRequest(
            "F1",
            ("lexical",),
            budget=RetrievalBudget(max_candidates=10),
        )
    )

    assert result.trace.rounds_used["conflict"] == 1
    assert result.trace.stop_reason == "conflict_unresolved"
    details = result.trace.corrective_details
    assert details["primary_reason"] == "metric_conflict"
    assert details["original_conflicts"][0]["conflict_type"] == "metric_value"
    assert details["candidate_changes"]["before"]
    assert details["candidate_changes"]["after"] == []
    assert details["filter_changes"]["section_scope"] == []
    assert details["unresolved_conflicts"]
