from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from paperclaw.entrypoint import main
from paperclaw.projects import ProjectManifestStore


def test_capabilities_cli_json_filter(capsys) -> None:
    status = main(
        [
            "capabilities",
            "--format",
            "json",
            "--status",
            "foundation",
            "--surface",
            "service",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["schema_version"] == 1
    assert payload["count"] > 0
    assert all(
        item["maturity"] == "foundation"
        and "service" in item["surfaces"]
        for item in payload["capabilities"]
    )


def test_project_cli_init_show_validate_index_refresh_and_watch(
    tmp_path: Path, capsys
) -> None:
    status = main(
        [
            "project",
            "--workspace",
            str(tmp_path),
            "init",
            "--name",
            "Interview Agent",
        ]
    )
    created = json.loads(capsys.readouterr().out)
    assert status == 0
    assert created["manifest"]["project_id"] == "interview-agent"

    (tmp_path / "PAPERCLAW.md").write_text(
        "Answer with grounded evidence.\n", encoding="utf-8"
    )
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    notes = knowledge / "notes.md"
    notes.write_text("MCP uses capability negotiation.\n", encoding="utf-8")
    store = ProjectManifestStore(tmp_path)
    manifest = replace(store.load(), knowledge_paths=("knowledge",))
    store.save(manifest)

    assert main(["project", "--workspace", str(tmp_path), "validate"]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["ok"] is True
    assert validated["index"]["reason"] == "index_missing"

    assert main(["project", "--workspace", str(tmp_path), "index"]) == 0
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["index"]["file_count"] == 1

    assert main(["project", "--workspace", str(tmp_path), "show"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["index"]["current"] is True
    assert shown["manifest"]["knowledge_paths"] == ["knowledge"]

    notes.write_text("MCP uses lifecycle negotiation.\n", encoding="utf-8")
    assert main(["project", "--workspace", str(tmp_path), "watch", "--once"]) == 0
    watched = json.loads(capsys.readouterr().out)
    assert watched["knowledge"]["status"]["reason"] == "index_stale"

    assert main(["project", "--workspace", str(tmp_path), "refresh"]) == 0
    refreshed = json.loads(capsys.readouterr().out)
    assert refreshed["rebuilt"] is True
    assert refreshed["knowledge"]["status"]["current"] is True
