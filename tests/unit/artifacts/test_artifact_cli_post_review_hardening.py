from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.entrypoint import main


def test_artifact_cli_rejects_source_symlink_inside_workspace(
    tmp_path: Path,
    capsys,
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "source.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    status = main(
        [
            "artifact",
            "--workspace",
            str(tmp_path),
            "create",
            "--type",
            "document",
            "--title",
            "Symlink",
            "--file",
            "source.txt",
            "--media-type",
            "text/plain",
            "--idempotency-key",
            "symlink",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert "non-symlink" in payload["error"]
    assert not (tmp_path / ".paperclaw" / "artifacts" / "artifacts.sqlite3").exists()


def test_artifact_cli_rejects_parent_storage_symlink_escape(
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    source = workspace / "source.txt"
    source.write_text("data", encoding="utf-8")
    try:
        (workspace / ".paperclaw").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    status = main(
        [
            "artifact",
            "--workspace",
            str(workspace),
            "create",
            "--type",
            "document",
            "--title",
            "Escape",
            "--file",
            "source.txt",
            "--media-type",
            "text/plain",
            "--idempotency-key",
            "escape",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert "escapes" in payload["error"]
    assert not (external / "artifacts" / "artifacts.sqlite3").exists()
