from __future__ import annotations

from pathlib import Path
import sqlite3

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


def test_incremental_version_sync_is_idempotent_and_keeps_explicit_history(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _indexed_runtime(tmp_path)
    first = AcademicObjectIndex(runtime).snapshot()
    source = tmp_path / "paper-v2.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "2 Revised Method", fontsize=18)
    page.insert_text((72, 110), "The revised detector uses sparse attention.")
    document.save(source)
    document.close()
    imported = runtime.papers.import_paper(
        PaperImportRequest(runtime.project_id, source, paper_id=paper_id)
    )
    parsed = runtime.parse_paper(paper_id)

    second = AcademicObjectIndex(runtime).sync_version(
        paper_id, imported.version.version_id
    )
    replay = AcademicObjectIndex(runtime).sync_version(
        paper_id, imported.version.version_id
    )

    assert second == replay
    assert {entry.version_id for entry in second.entries} == {
        *(entry.version_id for entry in first.entries),
        parsed.version_id,
    }
    old_version = first.entries[0].version_id
    assert runtime.retrieve(
        RetrievalRequest(
            "dual encoder",
            channels=("lexical",),
            version_ids=(old_version,),
        )
    ).candidates
    assert not runtime.retrieve(
        RetrievalRequest(
            "dual encoder",
            channels=("lexical",),
            paper_ids=(paper_id,),
        )
    ).candidates
    assert runtime.retrieve(
        RetrievalRequest(
            "sparse attention",
            channels=("lexical",),
            version_ids=(parsed.version_id,),
        )
    ).candidates


def test_deleted_version_has_no_ghost_hits_or_locator_after_restart(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _indexed_runtime(tmp_path)
    before = AcademicObjectIndex(runtime).snapshot()
    deleted_version = before.entries[0].version_id
    deleted_locator = before.entries[0].locator

    after = AcademicObjectIndex(runtime).delete_version(paper_id, deleted_version)

    assert all(entry.version_id != deleted_version for entry in after.entries)
    assert not runtime.retrieve(
        RetrievalRequest(
            "dual encoder",
            channels=("lexical",),
            version_ids=(deleted_version,),
        )
    ).candidates
    reopened = AcademicRuntime.for_workspace(tmp_path, runtime.project_id)
    with pytest.raises((KeyError, Exception), match="version|locator|not found"):
        reopened.resolve(deleted_locator)


def test_stale_manifest_digest_fails_closed_and_rebuild_recovers(
    tmp_path: Path,
) -> None:
    runtime, _ = _indexed_runtime(tmp_path)
    damaged_generation = AcademicObjectIndex(runtime).snapshot().generation_id
    with sqlite3.connect(runtime.database) as db:
        db.execute(
            """
            UPDATE academic_index_manifests
            SET content_hash=?
            WHERE generation_id=(SELECT generation_id FROM index_generations WHERE active=1)
            """,
            ("0" * 64,),
        )

    with pytest.raises(RuntimeError, match="manifest integrity"):
        AcademicObjectIndex(runtime).snapshot()

    recovered = AcademicObjectIndex(runtime).rebuild()
    assert recovered.generation_id != damaged_generation
    assert recovered.content_hash != "0" * 64


def test_failed_incremental_generation_keeps_previous_snapshot_visible(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _indexed_runtime(tmp_path)
    previous = AcademicObjectIndex(runtime).snapshot()
    source = tmp_path / "failed-v2.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "This generation must roll back.")
    document.save(source)
    document.close()
    imported = runtime.papers.import_paper(
        PaperImportRequest(runtime.project_id, source, paper_id=paper_id)
    )
    runtime.parse_paper(paper_id)
    with sqlite3.connect(runtime.database) as db:
        db.execute(
            """
            CREATE TRIGGER reject_new_academic_generation
            BEFORE INSERT ON academic_index
            WHEN NEW.generation_id <> (
                SELECT generation_id FROM index_generations WHERE active=1
            )
            BEGIN
                SELECT RAISE(ABORT, 'injected index failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected index failure"):
        AcademicObjectIndex(runtime).sync_version(paper_id, imported.version.version_id)

    assert AcademicObjectIndex(runtime).snapshot() == previous


def test_missing_persisted_row_rejects_search_and_explicit_rebuild_restores(
    tmp_path: Path,
) -> None:
    runtime, _ = _indexed_runtime(tmp_path)
    damaged_generation = AcademicObjectIndex(runtime).snapshot().generation_id
    with sqlite3.connect(runtime.database) as db:
        db.execute(
            """
            DELETE FROM academic_index
            WHERE generation_id=(SELECT generation_id FROM index_generations WHERE active=1)
              AND object_id=(
                  SELECT object_id FROM academic_index
                  WHERE generation_id=(
                      SELECT generation_id FROM index_generations WHERE active=1
                  )
                  LIMIT 1
              )
            """
        )

    with pytest.raises(RuntimeError, match="integrity"):
        RetrievalService(runtime).search(
            RetrievalRequest("dual encoder", channels=("lexical",))
        )

    recovered = AcademicObjectIndex(runtime).rebuild()
    assert recovered.generation_id != damaged_generation
    assert recovered.entries
    assert (
        RetrievalService(runtime)
        .search(RetrievalRequest("dual encoder", channels=("lexical",)))
        .hits
    )


def test_failed_canonical_version_delete_restores_previous_index_snapshot(
    tmp_path: Path,
) -> None:
    runtime, paper_id = _indexed_runtime(tmp_path)
    previous = AcademicObjectIndex(runtime).snapshot()
    version_id = previous.entries[0].version_id
    with runtime.papers.repository.transaction() as db:
        db.execute(
            """
            CREATE TRIGGER reject_paper_version_delete
            BEFORE DELETE ON paper_versions
            BEGIN
                SELECT RAISE(ABORT, 'injected version delete failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected version delete failure"):
        AcademicObjectIndex(runtime).delete_version(paper_id, version_id)

    assert AcademicObjectIndex(runtime).snapshot() == previous
    assert runtime.resolve(previous.entries[0].locator)
