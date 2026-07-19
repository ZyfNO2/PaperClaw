from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from paperclaw.projects import (
    ProjectIndexPolicy,
    ProjectKnowledgeRuntime,
    ProjectKnowledgeUnavailableError,
    ProjectManifest,
    ProjectManifestStore,
    build_project_index,
    inspect_project_index,
)


def _project(tmp_path: Path) -> tuple[ProjectManifestStore, ProjectManifest, Path]:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    document = knowledge / "facts.md"
    document.write_text("evidence\n", encoding="utf-8")
    manifest = ProjectManifest(
        schema_version=1,
        project_id="review-demo",
        name="Review Demo",
        instruction_files=(),
        knowledge_paths=("knowledge",),
    )
    store = ProjectManifestStore(tmp_path)
    store.save(manifest)
    return store, manifest, document


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_index_metadata_v2_is_bound_to_database_bytes(tmp_path: Path) -> None:
    store, manifest, _document = _project(tmp_path)
    report = build_project_index(store, manifest)
    database = tmp_path / report.database
    metadata = tmp_path / ".paperclaw" / "data" / "project-index.json"
    payload = json.loads(metadata.read_text(encoding="utf-8"))

    assert report.schema_version == 2
    assert payload["schema_version"] == 2
    assert report.database_sha256 == _sha256(database)
    assert payload["database_sha256"] == report.database_sha256
    assert inspect_project_index(store, manifest).current is True


def test_swapped_database_is_not_accepted_by_allow_stale(tmp_path: Path) -> None:
    store, manifest, document = _project(tmp_path)
    report = build_project_index(store, manifest)
    database = tmp_path / report.database
    database.write_bytes(database.read_bytes() + b"tampered")
    document.write_text("source also changed\n", encoding="utf-8")

    runtime = ProjectKnowledgeRuntime(
        store,
        manifest,
        policy=ProjectIndexPolicy.ALLOW_STALE,
    )
    snapshot = runtime.inspect()
    assert snapshot.status.reason == "index_database_mismatch"
    assert snapshot.retriever_available is False
    with pytest.raises(ProjectKnowledgeUnavailableError, match="database_mismatch"):
        runtime.create_retriever()


def test_legacy_schema_requires_rebuild(tmp_path: Path) -> None:
    store, manifest, _document = _project(tmp_path)
    build_project_index(store, manifest)
    metadata = tmp_path / ".paperclaw" / "data" / "project-index.json"
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    payload.pop("database_sha256")
    metadata.write_text(json.dumps(payload), encoding="utf-8")

    status = inspect_project_index(store, manifest)
    assert status.current is False
    assert status.reason.startswith("index_metadata_invalid")


def test_oversized_metadata_is_fail_closed(tmp_path: Path) -> None:
    store, manifest, _document = _project(tmp_path)
    build_project_index(store, manifest)
    metadata = tmp_path / ".paperclaw" / "data" / "project-index.json"
    metadata.write_bytes(b"{" + b" " * 1_048_576 + b"}")

    status = inspect_project_index(store, manifest)
    assert status.available is True
    assert status.current is False
    assert status.reason.startswith("index_metadata_invalid")


def test_symlinked_index_file_is_never_accepted(tmp_path: Path) -> None:
    store, manifest, _document = _project(tmp_path)
    build_project_index(store, manifest)
    metadata = tmp_path / ".paperclaw" / "data" / "project-index.json"
    external = tmp_path / "external-index.json"
    external.write_bytes(metadata.read_bytes())
    metadata.unlink()
    try:
        metadata.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    status = inspect_project_index(store, manifest)
    assert status.reason == "index_path_symlink"
    runtime = ProjectKnowledgeRuntime(
        store,
        manifest,
        policy=ProjectIndexPolicy.ALLOW_STALE,
    )
    assert runtime.inspect().retriever_available is False


def test_manifest_parent_symlink_cannot_redirect_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    paperclaw = workspace / ".paperclaw"
    try:
        paperclaw.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    store = ProjectManifestStore(workspace)
    manifest = ProjectManifest(
        schema_version=1,
        project_id="blocked",
        name="Blocked",
        instruction_files=(),
    )
    with pytest.raises(ValueError, match="escapes"):
        store.save(manifest)
    assert not (external / "project.json").exists()
