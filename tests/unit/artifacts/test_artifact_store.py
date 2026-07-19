from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
import queue

import pytest

from paperclaw.artifacts import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    ArtifactSourceLinks,
    FileArtifactStore,
)


def test_create_and_revise_are_append_only_and_idempotent(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    artifact, first, created = store.create_artifact(
        idempotency_key="create-1",
        artifact_type="report",
        title="Research Report",
        media_type="text/markdown",
        content=b"version one\n",
        source=ArtifactSourceLinks(
            project_id="project-1", run_id="run-1", trace_id="trace-1"
        ),
        metadata={"language": "zh-CN"},
    )
    retry_artifact, retry_revision, retry_created = store.create_artifact(
        idempotency_key="create-1",
        artifact_type="report",
        title="Research Report",
        media_type="text/markdown",
        content=b"version one\n",
        source=ArtifactSourceLinks(
            project_id="project-1", run_id="run-1", trace_id="trace-1"
        ),
        metadata={"language": "zh-CN"},
    )

    assert created is True
    assert retry_created is False
    assert retry_artifact == artifact
    assert retry_revision == first

    second, second_created = store.add_revision(
        artifact.artifact_id,
        idempotency_key="rev-2",
        media_type="text/markdown",
        content=b"version two\n",
        message="add evidence",
    )
    retry_second, retry_second_created = store.add_revision(
        artifact.artifact_id,
        idempotency_key="rev-2",
        media_type="text/markdown",
        content=b"version two\n",
        message="add evidence",
    )
    assert second_created is True
    assert retry_second_created is False
    assert retry_second == second
    assert second.revision_number == 2
    assert store.read_revision(artifact.artifact_id, 1) == b"version one\n"
    assert store.read_revision(artifact.artifact_id, 2) == b"version two\n"
    bundle = store.get_bundle(artifact.artifact_id)
    assert [item.revision_number for item in bundle.revisions] == [1, 2]
    assert bundle.artifact.latest_revision_number == 2


def test_idempotency_conflicts_fail_closed(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    artifact, _revision, _ = store.create_artifact(
        idempotency_key="create",
        artifact_type="document",
        title="Document",
        media_type="text/plain",
        content=b"one",
    )
    with pytest.raises(ArtifactConflictError):
        store.create_artifact(
            idempotency_key="create",
            artifact_type="document",
            title="Document",
            media_type="text/plain",
            content=b"different",
        )

    store.add_revision(
        artifact.artifact_id,
        idempotency_key="revise",
        media_type="text/plain",
        content=b"two",
    )
    with pytest.raises(ArtifactConflictError):
        store.add_revision(
            artifact.artifact_id,
            idempotency_key="revise",
            media_type="text/plain",
            content=b"different revision",
        )


def test_metadata_is_detached_and_secret_fields_rejected(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    metadata = {"nested": {"labels": ["a"]}}
    artifact, _revision, _ = store.create_artifact(
        idempotency_key="metadata",
        artifact_type="document",
        title="Metadata",
        media_type="text/plain",
        content=b"content",
        metadata=metadata,
    )
    metadata["nested"]["labels"].append("b")  # type: ignore[index,union-attr]
    assert artifact.to_dict()["metadata"] == {"nested": {"labels": ["a"]}}
    with pytest.raises(TypeError):
        artifact.metadata["changed"] = True  # type: ignore[index]

    with pytest.raises(ValueError, match="secret field"):
        store.create_artifact(
            idempotency_key="secret",
            artifact_type="document",
            title="Secret",
            media_type="text/plain",
            content=b"content",
            metadata={"nested": {"api_key": "forbidden"}},
        )


def test_export_is_root_bounded_and_does_not_overwrite_by_default(
    tmp_path: Path,
) -> None:
    store = FileArtifactStore(tmp_path / "store")
    artifact, _revision, _ = store.create_artifact(
        idempotency_key="export",
        artifact_type="report",
        title="Export",
        media_type="text/markdown",
        content=b"# report\n",
    )
    output = tmp_path / "output"
    output.mkdir()

    target = store.export_revision(
        artifact.artifact_id, output, "reports/final.md"
    )
    assert target.read_bytes() == b"# report\n"
    with pytest.raises(FileExistsError):
        store.export_revision(artifact.artifact_id, output, "reports/final.md")
    with pytest.raises(ValueError, match="stay within"):
        store.export_revision(artifact.artifact_id, output, "../escape.md")


def test_blob_integrity_is_verified_on_read(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    artifact, revision, _ = store.create_artifact(
        idempotency_key="integrity",
        artifact_type="data",
        title="Data",
        media_type="application/json",
        content=b"{}",
    )
    blob = store.blob_root / revision.content_hash[:2] / revision.content_hash
    blob.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError):
        store.read_revision(artifact.artifact_id)


def test_list_filters_by_project_and_type(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    store.create_artifact(
        idempotency_key="a",
        artifact_type="report",
        title="A",
        media_type="text/plain",
        content=b"a",
        source=ArtifactSourceLinks(project_id="alpha"),
    )
    store.create_artifact(
        idempotency_key="b",
        artifact_type="dataset",
        title="B",
        media_type="application/json",
        content=b"{}",
        source=ArtifactSourceLinks(project_id="beta"),
    )
    assert len(store.list_artifacts(project_id="alpha")) == 1
    assert len(store.list_artifacts(artifact_type="dataset")) == 1


def _append_process(
    root: str,
    artifact_id: str,
    index: int,
    output_queue,
) -> None:
    store = FileArtifactStore(root)
    revision, created = store.add_revision(
        artifact_id,
        idempotency_key=f"process-{index}",
        media_type="text/plain",
        content=f"revision {index}".encode(),
    )
    output_queue.put((revision.revision_number, created))


@pytest.mark.skipif(not hasattr(mp, "get_context"), reason="multiprocessing unavailable")
def test_multi_process_revision_append_remains_contiguous(tmp_path: Path) -> None:
    root = tmp_path / "store"
    store = FileArtifactStore(root)
    artifact, _revision, _ = store.create_artifact(
        idempotency_key="initial",
        artifact_type="document",
        title="Concurrent",
        media_type="text/plain",
        content=b"initial",
    )
    context = mp.get_context("spawn")
    output_queue = context.Queue()
    processes = [
        context.Process(
            target=_append_process,
            args=(str(root), artifact.artifact_id, index, output_queue),
        )
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    results = []
    for _ in processes:
        try:
            results.append(output_queue.get(timeout=5))
        except queue.Empty as exc:
            raise AssertionError("revision process returned no evidence") from exc
    assert all(created for _number, created in results)
    assert sorted(number for number, _created in results) == [2, 3, 4, 5]
    assert store.get_bundle(artifact.artifact_id).artifact.latest_revision_number == 5
