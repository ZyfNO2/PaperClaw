from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.projects import ProjectManifestStore, discover_project_manifest


def test_manifest_array_fields_reject_string_coercion(tmp_path: Path) -> None:
    store = ProjectManifestStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "demo",
                "name": "Demo",
                "instruction_files": "PAPERCLAW.md",
                "knowledge_paths": "knowledge",
                "enabled_skills": "review",
                "enabled_connectors": "local-mcp",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be an array"):
        store.load()


def test_manifest_path_cannot_be_symbolic_link(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "demo",
                "name": "Demo",
            }
        ),
        encoding="utf-8",
    )
    store = ProjectManifestStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    try:
        store.path.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    assert store.exists is True
    with pytest.raises(ValueError, match="symbolic link"):
        store.load()
    with pytest.raises(ValueError, match="symbolic link"):
        discover_project_manifest(tmp_path)
