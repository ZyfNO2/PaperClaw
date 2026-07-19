from __future__ import annotations

import json
from pathlib import Path

from paperclaw.entrypoint import main


def test_artifact_cli_create_revise_show_list_export(tmp_path: Path, capsys) -> None:
    first = tmp_path / "draft.md"
    first.write_text("# draft\n", encoding="utf-8")
    status = main(
        [
            "artifact",
            "--workspace",
            str(tmp_path),
            "create",
            "--type",
            "report",
            "--title",
            "Research Report",
            "--file",
            "draft.md",
            "--media-type",
            "text/markdown",
            "--idempotency-key",
            "create-report",
            "--project-id",
            "project-1",
            "--run-id",
            "run-1",
        ]
    )
    created = json.loads(capsys.readouterr().out)
    assert status == 0
    assert created["created"] is True
    artifact_id = created["artifact"]["artifact_id"]

    retry_status = main(
        [
            "artifact",
            "--workspace",
            str(tmp_path),
            "create",
            "--type",
            "report",
            "--title",
            "Research Report",
            "--file",
            "draft.md",
            "--media-type",
            "text/markdown",
            "--idempotency-key",
            "create-report",
            "--project-id",
            "project-1",
            "--run-id",
            "run-1",
        ]
    )
    retry = json.loads(capsys.readouterr().out)
    assert retry_status == 0
    assert retry["created"] is False
    assert retry["artifact"]["artifact_id"] == artifact_id

    second = tmp_path / "final.md"
    second.write_text("# final\n", encoding="utf-8")
    assert (
        main(
            [
                "artifact",
                "--workspace",
                str(tmp_path),
                "revise",
                artifact_id,
                "--file",
                "final.md",
                "--media-type",
                "text/markdown",
                "--idempotency-key",
                "revision-2",
                "--message",
                "finalize",
            ]
        )
        == 0
    )
    revised = json.loads(capsys.readouterr().out)
    assert revised["revision"]["revision_number"] == 2

    assert (
        main(
            [
                "artifact",
                "--workspace",
                str(tmp_path),
                "show",
                artifact_id,
            ]
        )
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert len(shown["bundle"]["revisions"]) == 2

    assert (
        main(
            [
                "artifact",
                "--workspace",
                str(tmp_path),
                "list",
                "--project-id",
                "project-1",
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 1

    output = tmp_path / "exports"
    output.mkdir()
    assert (
        main(
            [
                "artifact",
                "--workspace",
                str(tmp_path),
                "export",
                artifact_id,
                "--destination-root",
                str(output),
                "--path",
                "report.md",
            ]
        )
        == 0
    )
    exported = json.loads(capsys.readouterr().out)
    assert Path(exported["exported_path"]).read_text(encoding="utf-8") == "# final\n"


def test_artifact_cli_rejects_source_outside_workspace(tmp_path: Path, capsys) -> None:
    outside = tmp_path.parent / "outside-artifact.txt"
    outside.write_text("outside", encoding="utf-8")
    status = main(
        [
            "artifact",
            "--workspace",
            str(tmp_path),
            "create",
            "--type",
            "document",
            "--title",
            "Outside",
            "--file",
            str(outside),
            "--media-type",
            "text/plain",
            "--idempotency-key",
            "outside",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert "inside workspace" in payload["error"]
