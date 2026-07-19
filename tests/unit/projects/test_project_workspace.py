from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.context import ContextRequest
from paperclaw.memory import MemoryRuntimeSettings, build_memory_runtime
from paperclaw.projects import (
    ProjectManifest,
    ProjectManifestStore,
    build_project_index,
    inspect_project_index,
)


def _manifest(**overrides) -> ProjectManifest:
    values = {
        "schema_version": 1,
        "project_id": "demo-project",
        "name": "Demo Project",
        "instruction_files": ("PROJECT.md",),
        "knowledge_paths": ("knowledge",),
        "enabled_skills": ("review",),
        "enabled_connectors": ("local-mcp",),
        "data_directory": ".paperclaw/data",
    }
    values.update(overrides)
    return ProjectManifest(**values)


def test_project_manifest_roundtrip_and_validation(tmp_path: Path) -> None:
    (tmp_path / "PROJECT.md").write_text("Use evidence.\n", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "facts.md").write_text(
        "The launch code is cobalt-42.\n", encoding="utf-8"
    )
    store = ProjectManifestStore(tmp_path)
    manifest = _manifest()

    store.save(manifest)
    loaded = store.load()
    report = store.validate(loaded)

    assert loaded == manifest
    assert report.ok is True
    persisted = json.loads(store.path.read_text(encoding="utf-8"))
    assert persisted["project_id"] == "demo-project"
    assert "api_key" not in persisted


def test_manifest_rejects_unknown_secret_and_traversal_fields(tmp_path: Path) -> None:
    store = ProjectManifestStore(tmp_path)
    store.path.parent.mkdir(parents=True)

    store.path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "demo",
                "name": "Demo",
                "api_key": "should-not-exist",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown project manifest fields"):
        store.load()

    with pytest.raises(ValueError, match="workspace"):
        _manifest(knowledge_paths=("../outside",))
    with pytest.raises(ValueError, match="workspace"):
        _manifest(data_directory="/tmp/outside")


def test_project_index_is_deterministic_and_reports_staleness(tmp_path: Path) -> None:
    (tmp_path / "PROJECT.md").write_text("Use evidence.\n", encoding="utf-8")
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "b.txt").write_text("beta evidence\n", encoding="utf-8")
    (knowledge / "a.md").write_text("alpha evidence\n", encoding="utf-8")
    (knowledge / "ignored.bin").write_bytes(b"\x00\x01")
    store = ProjectManifestStore(tmp_path)
    manifest = _manifest()
    store.save(manifest)

    first = build_project_index(store, manifest)
    current = inspect_project_index(store, manifest)

    assert first.file_count == 2
    assert [item.relative_path for item in first.indexed_files] == [
        "knowledge/a.md",
        "knowledge/b.txt",
    ]
    assert current.available is True
    assert current.current is True

    (knowledge / "a.md").write_text("changed evidence\n", encoding="utf-8")
    stale = inspect_project_index(store, manifest)
    assert stale.current is False
    assert stale.reason == "index_stale"

    second = build_project_index(store, manifest)
    assert second.source_fingerprint != first.source_fingerprint
    assert inspect_project_index(store, manifest).current is True


def test_runtime_uses_manifest_instructions_and_only_current_project_index(
    tmp_path: Path,
) -> None:
    (tmp_path / "PROJECT.md").write_text(
        "PROJECT-CONSTRAINT-ONLY\n", encoding="utf-8"
    )
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "facts.md").write_text(
        "cobalt-42 is the verified launch code\n", encoding="utf-8"
    )
    store = ProjectManifestStore(tmp_path)
    manifest = _manifest()
    store.save(manifest)
    build_project_index(store, manifest)

    runtime = build_memory_runtime(
        tmp_path,
        settings=MemoryRuntimeSettings(memory_root=tmp_path / "memory"),
    )
    try:
        descriptors = runtime.source_registry.snapshot().descriptors
        assert {item.source_id for item in descriptors} == {
            "foundational_context",
            "project.bm25_retrieval",
        }
        candidates = runtime.source_registry.collect(
            ContextRequest(
                run_id="run-project",
                conversation_id="conversation-project",
                step_id="step-project",
                raw_prompt="[Task]\nWhat is the launch code?\n[History]\n[]",
                workspace=str(tmp_path),
            )
        )
        assert any("PROJECT-CONSTRAINT-ONLY" in item.content for item in candidates)
        assert any("cobalt-42" in item.content for item in candidates)
        assert runtime.project_index_status is not None
        assert runtime.project_index_status.current is True
    finally:
        runtime.close()

    (knowledge / "facts.md").write_text("new data\n", encoding="utf-8")
    stale_runtime = build_memory_runtime(
        tmp_path,
        settings=MemoryRuntimeSettings(memory_root=tmp_path / "memory-2"),
    )
    try:
        ids = {
            item.source_id
            for item in stale_runtime.source_registry.snapshot().descriptors
        }
        assert "project.bm25_retrieval" not in ids
        assert stale_runtime.project_index_status is not None
        assert stale_runtime.project_index_status.reason == "index_stale"
    finally:
        stale_runtime.close()
