from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import threading

import pytest

from paperclaw.artifacts import (
    ArtifactCapacityError,
    ArtifactConflictError,
    ArtifactNotFoundError,
    FileArtifactStore,
)


def _blob_path(store: FileArtifactStore, content: bytes) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    return store.blob_root / digest[:2] / digest


def test_confinement_rejects_parent_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    paperclaw = workspace / ".paperclaw"
    try:
        paperclaw.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    with pytest.raises(ValueError, match="escapes"):
        FileArtifactStore(
            paperclaw / "artifacts",
            confinement_root=workspace,
        )
    assert not (external / "artifacts" / "artifacts.sqlite3").exists()


def test_invalid_and_conflicting_requests_do_not_create_new_blobs(
    tmp_path: Path,
) -> None:
    store = FileArtifactStore(tmp_path / "store")
    artifact, _revision, _created = store.create_artifact(
        idempotency_key="create",
        artifact_type="document",
        title="Document",
        media_type="text/plain",
        content=b"original",
    )

    conflicting = b"conflicting-create"
    with pytest.raises(ArtifactConflictError):
        store.create_artifact(
            idempotency_key="create",
            artifact_type="document",
            title="Document",
            media_type="text/plain",
            content=conflicting,
        )
    assert not _blob_path(store, conflicting).exists()

    missing = b"missing-artifact"
    with pytest.raises(ArtifactNotFoundError):
        store.add_revision(
            "artifact-does-not-exist",
            idempotency_key="missing",
            media_type="text/plain",
            content=missing,
        )
    assert not _blob_path(store, missing).exists()

    invalid = b"invalid-media-type"
    with pytest.raises(ValueError, match="media_type"):
        store.add_revision(
            artifact.artifact_id,
            idempotency_key="invalid",
            media_type="not-a-media-type",
            content=invalid,
        )
    assert not _blob_path(store, invalid).exists()


def test_exact_count_is_independent_of_list_limit(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    for index in range(12):
        store.create_artifact(
            idempotency_key=f"artifact-{index}",
            artifact_type="report",
            title=f"Report {index}",
            media_type="text/plain",
            content=str(index).encode(),
        )

    assert len(store.list_artifacts(limit=3)) == 3
    assert store.count_artifacts() == 12
    assert store.count_artifacts(artifact_type="report") == 12


def test_revision_history_limit_fails_before_returning_unbounded_bundle(
    tmp_path: Path,
) -> None:
    store = FileArtifactStore(tmp_path / "store")
    artifact, _revision, _created = store.create_artifact(
        idempotency_key="initial",
        artifact_type="document",
        title="History",
        media_type="text/plain",
        content=b"r1",
    )
    for number in range(2, 5):
        store.add_revision(
            artifact.artifact_id,
            idempotency_key=f"r{number}",
            media_type="text/plain",
            content=f"r{number}".encode(),
        )

    with pytest.raises(ArtifactCapacityError, match="history"):
        store.get_bundle(artifact.artifact_id, max_revisions=3)
    assert len(store.get_bundle(artifact.artifact_id, max_revisions=4).revisions) == 4


def test_concurrent_no_clobber_exports_have_one_complete_winner(
    tmp_path: Path,
) -> None:
    store = FileArtifactStore(tmp_path / "store")
    first, _revision, _created = store.create_artifact(
        idempotency_key="first",
        artifact_type="document",
        title="First",
        media_type="text/plain",
        content=b"first-complete-payload",
    )
    second, _revision, _created = store.create_artifact(
        idempotency_key="second",
        artifact_type="document",
        title="Second",
        media_type="text/plain",
        content=b"second-complete-payload",
    )
    output = tmp_path / "output"
    output.mkdir()
    barrier = threading.Barrier(2)

    def export(artifact_id: str) -> str:
        barrier.wait(timeout=5)
        try:
            store.export_revision(artifact_id, output, "winner.txt")
            return "created"
        except FileExistsError:
            return "exists"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(export, (first.artifact_id, second.artifact_id)))

    assert sorted(outcomes) == ["created", "exists"]
    assert (output / "winner.txt").read_bytes() in {
        b"first-complete-payload",
        b"second-complete-payload",
    }


def test_export_rejects_platform_specific_path_tricks(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    artifact, _revision, _created = store.create_artifact(
        idempotency_key="paths",
        artifact_type="document",
        title="Paths",
        media_type="text/plain",
        content=b"data",
    )
    output = tmp_path / "output"
    output.mkdir()

    for path in ("CON", "report.txt:stream", "trailing. ", "a//b.txt"):
        with pytest.raises(ValueError):
            store.export_revision(artifact.artifact_id, output, path)
