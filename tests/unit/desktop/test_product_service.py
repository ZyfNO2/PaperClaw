from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.artifacts import ArtifactSourceLinks, FileArtifactStore
from paperclaw.desktop.contracts import DesktopPublicError
from paperclaw.desktop.product_service import DesktopProductService
from paperclaw.projects import ProjectManifest, ProjectManifestStore, build_project_index


def _project(tmp_path: Path) -> tuple[ProjectManifestStore, ProjectManifest, Path]:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    document = knowledge / "facts.md"
    document.write_text("grounded evidence\n", encoding="utf-8")
    manifest = ProjectManifest(
        schema_version=1,
        project_id="desktop-project",
        name="Desktop Project",
        instruction_files=(),
        knowledge_paths=("knowledge",),
        enabled_skills=("review",),
        enabled_connectors=("local-mcp",),
    )
    store = ProjectManifestStore(tmp_path)
    store.save(manifest)
    return store, manifest, document


def test_capability_catalog_exposes_current_stack_without_credentials() -> None:
    response = DesktopProductService().get_capabilities()
    values = response["catalog"]["capabilities"]  # type: ignore[index]
    by_id = {item["capability_id"]: item for item in values}  # type: ignore[index]

    assert by_id["project.knowledge_runtime"]["introduced_version"] == "v0.28"
    assert by_id["artifact.revisions"]["introduced_version"] == "v0.29"
    assert by_id["desktop.product_management"]["introduced_version"] == "v0.30"
    serialized = json.dumps(response, sort_keys=True).lower()
    assert "api_key" not in serialized
    assert "authorization" not in serialized


def test_project_status_absent_current_stale_and_refresh(tmp_path: Path) -> None:
    service = DesktopProductService()
    absent = service.get_project_status(str(tmp_path))
    assert absent["project"]["state"] == "absent"  # type: ignore[index]

    store, manifest, document = _project(tmp_path)
    build_project_index(store, manifest)
    current = service.get_project_status(str(tmp_path))
    assert current["project"]["state"] == "current"  # type: ignore[index]
    assert current["project"]["manifest"]["enabled_skills"] == ["review"]  # type: ignore[index]

    document.write_text("changed evidence\n", encoding="utf-8")
    stale = service.get_project_status(str(tmp_path))
    assert stale["project"]["state"] == "index_stale"  # type: ignore[index]

    refreshed = service.refresh_project_index(str(tmp_path))
    assert refreshed["rebuilt"] is True
    assert refreshed["knowledge"]["status"]["current"] is True  # type: ignore[index]


def test_invalid_manifest_is_reported_as_bounded_product_state(tmp_path: Path) -> None:
    manifest = tmp_path / ".paperclaw" / "project.json"
    manifest.parent.mkdir()
    manifest.write_text("{invalid", encoding="utf-8")

    response = DesktopProductService().get_project_status(str(tmp_path))
    assert response["ok"] is True
    project = response["project"]
    assert project["state"] == "invalid"  # type: ignore[index]
    issue = project["validation"]["issues"][0]  # type: ignore[index]
    assert issue["code"] == "manifest_invalid"
    assert len(issue["message"]) <= 500


def test_artifact_list_detail_and_workspace_local_export(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / ".paperclaw" / "artifacts")
    artifact, first, _ = store.create_artifact(
        idempotency_key="desktop-create",
        artifact_type="report",
        title="Desktop Report",
        media_type="text/markdown",
        content=b"# first\n",
        source=ArtifactSourceLinks(
            project_id="desktop-project", run_id="run-1", trace_id="trace-1"
        ),
    )
    store.add_revision(
        artifact.artifact_id,
        idempotency_key="desktop-revise",
        media_type="text/markdown",
        content=b"# final\n",
        message="final",
    )

    service = DesktopProductService()
    listed = service.list_artifacts(str(tmp_path), {"project_id": "desktop-project"})
    assert listed["count"] == 1
    assert listed["artifacts"][0]["artifact_id"] == artifact.artifact_id  # type: ignore[index]

    detail = service.get_artifact(str(tmp_path), artifact.artifact_id)
    assert [
        item["revision_number"]
        for item in detail["bundle"]["revisions"]  # type: ignore[index]
    ] == [1, 2]

    exported = service.export_artifact(str(tmp_path), artifact.artifact_id)
    target = Path(exported["exported_path"])
    assert target.read_bytes() == b"# final\n"
    assert target.is_relative_to(tmp_path / ".paperclaw" / "exports")
    assert exported["workspace_relative_path"].startswith(".paperclaw/exports/")
    assert first.revision_number == 1

    with pytest.raises(DesktopPublicError) as exc:
        service.export_artifact(
            str(tmp_path), artifact.artifact_id, "../escape.md"
        )
    assert exc.value.code == "validation_error"


def test_artifact_api_does_not_create_store_during_read(tmp_path: Path) -> None:
    root = tmp_path / ".paperclaw" / "artifacts"
    response = DesktopProductService().list_artifacts(str(tmp_path))
    assert response == {"ok": True, "count": 0, "artifacts": []}
    assert root.exists() is False


def test_workspace_and_artifact_symlinks_are_rejected(tmp_path: Path) -> None:
    service = DesktopProductService()
    linked = tmp_path.parent / f"{tmp_path.name}-link"
    try:
        linked.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")
    try:
        with pytest.raises(DesktopPublicError) as exc:
            service.get_project_status(str(linked))
        assert exc.value.code == "workspace_policy_denied"
    finally:
        linked.unlink(missing_ok=True)


def test_unknown_artifact_filters_and_bounds_are_rejected(tmp_path: Path) -> None:
    service = DesktopProductService()
    with pytest.raises(DesktopPublicError) as exc:
        service.list_artifacts(str(tmp_path), {"database": "outside.sqlite"})
    assert exc.value.code == "validation_error"

    with pytest.raises(DesktopPublicError):
        service.list_artifacts(str(tmp_path), {"limit": "100"})
