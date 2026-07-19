from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.projects import (
    ProjectIndexPolicy,
    ProjectKnowledgeRuntime,
    ProjectKnowledgeUnavailableError,
    ProjectManifest,
    ProjectManifestStore,
    build_project_index,
)


def test_allow_stale_rejects_invalid_metadata(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "facts.md").write_text("evidence\n", encoding="utf-8")
    manifest = ProjectManifest(
        schema_version=1,
        project_id="demo",
        name="Demo",
        instruction_files=(),
        knowledge_paths=("knowledge",),
    )
    store = ProjectManifestStore(tmp_path)
    store.save(manifest)
    build_project_index(store, manifest)
    metadata = tmp_path / ".paperclaw" / "data" / "project-index.json"
    metadata.write_text("{broken", encoding="utf-8")

    runtime = ProjectKnowledgeRuntime(
        store,
        manifest,
        policy=ProjectIndexPolicy.ALLOW_STALE,
    )
    snapshot = runtime.inspect()
    assert snapshot.status.reason.startswith("index_metadata_invalid")
    assert snapshot.retriever_available is False
    with pytest.raises(ProjectKnowledgeUnavailableError):
        runtime.create_retriever()
