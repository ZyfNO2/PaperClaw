from __future__ import annotations

from pathlib import Path

from paperclaw.memory import (
    MemoryRuntimeSettings,
    ProjectScopedMemoryStore,
    build_memory_runtime,
)
from paperclaw.projects import ProjectManifest, ProjectManifestStore


def test_project_memory_is_isolated_while_user_profile_is_global(tmp_path: Path) -> None:
    root = tmp_path / "memory-root"
    alpha = ProjectScopedMemoryStore(root, "alpha")
    beta = ProjectScopedMemoryStore(root, "beta")

    alpha.add("memory", "alpha-only lesson", category="project")
    alpha.add("user", "prefers concise answers", category="preference")
    beta.add("memory", "beta-only lesson", category="project")

    alpha_snapshot = alpha.snapshot()
    beta_snapshot = beta.snapshot()
    assert [entry.content for entry in alpha_snapshot.memory_entries] == [
        "alpha-only lesson"
    ]
    assert [entry.content for entry in beta_snapshot.memory_entries] == [
        "beta-only lesson"
    ]
    assert [entry.content for entry in alpha_snapshot.user_entries] == [
        "prefers concise answers"
    ]
    assert [entry.content for entry in beta_snapshot.user_entries] == [
        "prefers concise answers"
    ]
    assert alpha.paths.project_root != beta.paths.project_root


def test_runtime_uses_project_namespace_by_default(tmp_path: Path) -> None:
    ProjectManifestStore(tmp_path).save(
        ProjectManifest(
            schema_version=1,
            project_id="runtime-project",
            name="Runtime Project",
            instruction_files=(),
            knowledge_paths=(),
        )
    )
    settings = MemoryRuntimeSettings(memory_root=tmp_path / "memories")

    runtime = build_memory_runtime(tmp_path, settings=settings)
    try:
        assert isinstance(runtime.store, ProjectScopedMemoryStore)
        runtime.store.add("memory", "project convention", category="convention")
        runtime.store.add("user", "global preference", category="preference")
    finally:
        runtime.close()

    second = build_memory_runtime(tmp_path, settings=settings)
    try:
        assert [entry.content for entry in second.snapshot.memory_entries] == [
            "project convention"
        ]
        assert [entry.content for entry in second.snapshot.user_entries] == [
            "global preference"
        ]
    finally:
        second.close()


def test_runtime_can_disable_project_memory_isolation(tmp_path: Path) -> None:
    ProjectManifestStore(tmp_path).save(
        ProjectManifest(
            schema_version=1,
            project_id="legacy-memory",
            name="Legacy Memory",
            instruction_files=(),
            knowledge_paths=(),
        )
    )
    runtime = build_memory_runtime(
        tmp_path,
        settings=MemoryRuntimeSettings(
            memory_root=tmp_path / "memories",
            project_memory_isolation=False,
        ),
    )
    try:
        assert not isinstance(runtime.store, ProjectScopedMemoryStore)
    finally:
        runtime.close()
