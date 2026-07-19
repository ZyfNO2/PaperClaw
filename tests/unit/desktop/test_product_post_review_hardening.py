from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.artifacts import FileArtifactStore
from paperclaw.desktop.contracts import DesktopPublicError
from paperclaw.desktop.product_service import DesktopProductService


def test_desktop_rejects_parent_symlinked_artifact_storage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    paperclaw = workspace / ".paperclaw"
    try:
        paperclaw.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    with pytest.raises(DesktopPublicError) as exc:
        DesktopProductService().list_artifacts(str(workspace))
    assert exc.value.code == "artifact_policy_denied"
    assert not (external / "artifacts" / "artifacts.sqlite3").exists()


def test_desktop_rejects_symlinked_export_root(tmp_path: Path) -> None:
    store = FileArtifactStore(
        tmp_path / ".paperclaw" / "artifacts",
        confinement_root=tmp_path,
    )
    artifact, _revision, _created = store.create_artifact(
        idempotency_key="export",
        artifact_type="report",
        title="Report",
        media_type="text/plain",
        content=b"report",
    )
    external = tmp_path / "external"
    external.mkdir()
    export_root = tmp_path / ".paperclaw" / "exports"
    try:
        export_root.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    with pytest.raises(DesktopPublicError) as exc:
        DesktopProductService().export_artifact(str(tmp_path), artifact.artifact_id)
    assert exc.value.code == "artifact_policy_denied"
    assert not tuple(external.iterdir())


def test_desktop_overview_reports_exact_count_and_bounded_recent_rows(
    tmp_path: Path,
) -> None:
    store = FileArtifactStore(
        tmp_path / ".paperclaw" / "artifacts",
        confinement_root=tmp_path,
    )
    for index in range(12):
        store.create_artifact(
            idempotency_key=f"artifact-{index}",
            artifact_type="report",
            title=f"Report {index}",
            media_type="text/plain",
            content=str(index).encode(),
        )

    overview = DesktopProductService().get_overview(str(tmp_path))["overview"]
    assert overview["artifact_count"] == 12  # type: ignore[index]
    assert len(overview["recent_artifacts"]) == 10  # type: ignore[index]


def test_desktop_rejects_unbounded_revision_history(tmp_path: Path) -> None:
    store = FileArtifactStore(
        tmp_path / ".paperclaw" / "artifacts",
        confinement_root=tmp_path,
    )
    artifact, _revision, _created = store.create_artifact(
        idempotency_key="initial",
        artifact_type="document",
        title="Long History",
        media_type="text/plain",
        content=b"r1",
    )
    for number in range(2, 102):
        store.add_revision(
            artifact.artifact_id,
            idempotency_key=f"r{number}",
            media_type="text/plain",
            content=f"r{number}".encode(),
        )

    with pytest.raises(DesktopPublicError) as exc:
        DesktopProductService().get_artifact(str(tmp_path), artifact.artifact_id)
    assert exc.value.code == "artifact_too_large"
