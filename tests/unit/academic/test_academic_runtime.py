from __future__ import annotations

from pathlib import Path

import fitz

from paperclaw.academic import (
    AcademicQuery,
    AcademicRuntime,
    RetrievalBudget,
)
from paperclaw.papers import PaperImportRequest, PaperService
from paperclaw.projects import ProjectManifestStore


def _runtime(tmp_path: Path) -> tuple[AcademicRuntime, str]:
    manifest = ProjectManifestStore(tmp_path).initialize("Academic")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "1 Introduction", fontsize=18)
    page.insert_text((72, 110), "Concrete crack evidence appears on this page.")
    page.draw_rect(fitz.Rect(72, 150, 240, 230))
    source = tmp_path / "paper.pdf"
    document.save(source)
    document.close()
    papers = PaperService.for_workspace(tmp_path, project_id=manifest.project_id)
    imported = papers.import_paper(PaperImportRequest(manifest.project_id, source))
    return AcademicRuntime.for_workspace(tmp_path, manifest.project_id), imported.paper.paper_id


def test_parse_index_retrieve_resolve_and_evidence_bundle(tmp_path: Path) -> None:
    runtime, paper_id = _runtime(tmp_path)
    parsed = runtime.parse_paper(paper_id)
    assert parsed.status == "ready"
    assert parsed.page_count == 1
    assert {"document", "page", "section", "paragraph"} <= {
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
