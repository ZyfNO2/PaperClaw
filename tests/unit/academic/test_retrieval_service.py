from __future__ import annotations

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from paperclaw.academic import AcademicRuntime, RetrievalRequest  # noqa: E402
from paperclaw.academic.index import AcademicObjectIndex  # noqa: E402
from paperclaw.academic.retrieval_service import RetrievalService  # noqa: E402
from paperclaw.papers import PaperImportRequest, PaperService  # noqa: E402
from paperclaw.projects import ProjectManifestStore  # noqa: E402


def _indexed_runtime(tmp_path: Path) -> tuple[AcademicRuntime, str]:
    manifest = ProjectManifestStore(tmp_path).initialize("Academic retrieval")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "1 Method", fontsize=18)
    page.insert_text((72, 110), "The fracture detector uses a dual encoder.")
    page.draw_rect(fitz.Rect(72, 150, 240, 230))
    source = tmp_path / "paper.pdf"
    document.save(source)
    document.close()
    papers = PaperService.for_workspace(tmp_path, project_id=manifest.project_id)
    imported = papers.import_paper(PaperImportRequest(manifest.project_id, source))
    runtime = AcademicRuntime.for_workspace(tmp_path, manifest.project_id)
    runtime.parse_paper(imported.paper.paper_id)
    runtime.build_index()
    return runtime, imported.paper.paper_id


def test_search_returns_grounded_objects_neighbors_and_content_addressed_assets(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _indexed_runtime(tmp_path)
    service = RetrievalService(runtime)

    response = service.search(
        RetrievalRequest(
            "dual encoder",
            channels=("lexical",),
            paper_ids=(paper_id,),
        ),
        include_assets=True,
        include_neighbor_context=True,
    )

    assert response.result.candidates
    hit = response.hits[0]
    assert hit.object.locator == response.result.candidates[0].locator
    assert hit.neighbor_context
    assert all(asset.asset_hash for asset in hit.assets)
    assert response.bundle.candidates == response.result.candidates


def test_locator_and_asset_readback_remain_valid_after_service_restart(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _indexed_runtime(tmp_path)
    service = RetrievalService(runtime)
    response = service.search(
        RetrievalRequest(
            "fracture detector",
            channels=("lexical",),
            paper_ids=(paper_id,),
        ),
        include_assets=True,
    )
    hit = response.hits[0]
    asset = hit.assets[0]

    reopened = RetrievalService(
        AcademicRuntime.for_workspace(tmp_path, runtime.project_id)
    )

    assert reopened.resolve_locator(hit.object.locator) == hit.object
    assert reopened.read_asset(hit.object.locator, asset.asset_hash).startswith(
        b"\x89PNG\r\n\x1a\n"
    )


def test_search_rejects_unbounded_asset_requests() -> None:
    with pytest.raises(ValueError, match="asset byte budget"):
        RetrievalService.validate_options(
            include_assets=True,
            include_neighbor_context=False,
            neighbor_count=0,
            max_asset_bytes=0,
        )


def test_index_manifest_is_object_aware_deterministic_and_restart_safe(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _indexed_runtime(tmp_path)
    first = AcademicObjectIndex(runtime).snapshot()

    assert first.index_version == "academic-object-index.v1"
    assert first.entries
    assert {entry.paper_id for entry in first.entries} == {paper_id}
    assert all(entry.source_hash and entry.object_type for entry in first.entries)
    assert any(entry.asset_hashes for entry in first.entries)

    reopened = AcademicRuntime.for_workspace(tmp_path, runtime.project_id)
    second = AcademicObjectIndex(reopened).snapshot()

    assert second == first
