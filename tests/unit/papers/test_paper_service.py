from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from paperclaw.papers import (
    MetadataPatch,
    PaperConflictError,
    PaperImportRequest,
    PaperService,
)


def _project(tmp_path: Path) -> tuple[Path, PaperService]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace, PaperService.for_workspace(workspace, project_id="demo")


def test_import_txt_is_managed_and_survives_source_removal(tmp_path: Path) -> None:
    workspace, service = _project(tmp_path)
    source = workspace / "Evidence Note.txt"
    source.write_text("reproducible evidence", encoding="utf-8")

    result = service.import_paper(PaperImportRequest("demo", source))
    source.unlink()

    assert result.created is True
    assert result.paper.metadata.title.value == "Evidence Note"
    assert result.paper.metadata.title.status == "candidate"
    assert service.read_version(
        "demo", result.paper.paper_id, result.version.version_id
    ) == b"reproducible evidence"
    assert ".paperclaw" not in str(result.version.to_public_dict())


def test_import_is_idempotent_and_explicit_version_append_preserves_history(
    tmp_path: Path,
) -> None:
    workspace, service = _project(tmp_path)
    source = workspace / "paper.md"
    source.write_text("---\ntitle: First title\nauthors: A; B\nyear: 2025\n---\nBody", encoding="utf-8")
    first = service.import_paper(PaperImportRequest("demo", source))
    duplicate = service.import_paper(PaperImportRequest("demo", source))
    source.write_text("# Revised\nNew body", encoding="utf-8")
    second = service.import_paper(
        PaperImportRequest("demo", source, paper_id=first.paper.paper_id)
    )

    assert duplicate.created is False
    assert duplicate.version.version_id == first.version.version_id
    assert second.version.version_number == 2
    assert len(service.list_versions("demo", first.paper.paper_id)) == 2
    assert service.read_version(
        "demo", first.paper.paper_id, first.version.version_id
    ).endswith(b"Body")


def test_metadata_confirmation_uses_optimistic_concurrency(tmp_path: Path) -> None:
    workspace, service = _project(tmp_path)
    source = workspace / "paper.txt"
    source.write_text("body", encoding="utf-8")
    imported = service.import_paper(PaperImportRequest("demo", source))

    confirmed = service.confirm_metadata(
        "demo",
        imported.paper.paper_id,
        MetadataPatch(title="Confirmed title", doi="10.1000/example"),
        expected_revision=1,
    )

    assert confirmed.metadata_revision == 2
    assert confirmed.metadata.title.status == "confirmed"
    with pytest.raises(PaperConflictError):
        service.confirm_metadata(
            "demo",
            imported.paper.paper_id,
            MetadataPatch(title="stale"),
            expected_revision=1,
        )


@pytest.mark.parametrize("name", ["paper.exe", "paper.tex"])
def test_import_rejects_unsupported_formats(tmp_path: Path, name: str) -> None:
    workspace, service = _project(tmp_path)
    source = workspace / name
    source.write_text("body", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        service.import_paper(PaperImportRequest("demo", source))


def test_import_rejects_invalid_text_and_damaged_pdf(tmp_path: Path) -> None:
    workspace, service = _project(tmp_path)
    invalid_text = workspace / "bad.txt"
    invalid_text.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="UTF-8"):
        service.import_paper(PaperImportRequest("demo", invalid_text))

    invalid_pdf = workspace / "bad.pdf"
    invalid_pdf.write_bytes(b"not a pdf")
    with pytest.raises(ValueError, match="PDF"):
        service.import_paper(PaperImportRequest("demo", invalid_pdf))

    truncated_pdf = workspace / "truncated.pdf"
    truncated_pdf.write_bytes(b"%PDF-1.7\ntruncated")
    with pytest.raises(ValueError, match="PDF"):
        service.import_paper(PaperImportRequest("demo", truncated_pdf))


def test_concurrent_same_hash_import_is_idempotent_and_replayable(tmp_path: Path) -> None:
    workspace, first_service = _project(tmp_path)
    second_service = PaperService.for_workspace(workspace, project_id="demo")
    source = workspace / "concurrent.txt"
    source.write_text("shared bytes", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda service: service.import_paper(PaperImportRequest("demo", source)),
                (first_service, second_service),
            )
        )

    assert sorted(result.created for result in results) == [False, True]
    assert results[0].version.version_id == results[1].version.version_id
    assert len(first_service.list_papers("demo")) == 1
    assert first_service.read_version(
        "demo", results[0].paper.paper_id, results[0].version.version_id
    ) == b"shared bytes"


def test_existing_corrupt_blob_fails_before_database_insert(tmp_path: Path) -> None:
    workspace, service = _project(tmp_path)
    source = workspace / "paper.txt"
    source.write_text("expected", encoding="utf-8")
    import hashlib

    digest = hashlib.sha256(b"expected").hexdigest()
    blob = workspace / ".paperclaw" / "papers" / "blobs" / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"corrupt")

    with pytest.raises(RuntimeError, match="integrity"):
        service.import_paper(PaperImportRequest("demo", source))
    assert service.list_papers("demo") == ()
