from __future__ import annotations

import json

from fastapi.testclient import TestClient

from paperclaw.papers.cli import main
from paperclaw.projects import ProjectManifestStore
from paperclaw.service.fastapi_app import create_app


class EmptyService:
    pass


def _workspace(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir(parents=True)
    ProjectManifestStore(workspace).initialize("Demo")
    return workspace


def test_cli_import_list_show_and_versions_share_projection(tmp_path, capsys) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "paper.txt"
    source.write_text("body", encoding="utf-8")

    assert main(["--workspace", str(workspace), "import", str(source)]) == 0
    imported = json.loads(capsys.readouterr().out)
    paper_id = imported["paper"]["paper_id"]
    assert ".paperclaw" not in json.dumps(imported)

    assert main(["--workspace", str(workspace), "list"]) == 0
    assert json.loads(capsys.readouterr().out)["papers"][0]["paper_id"] == paper_id
    assert main(["--workspace", str(workspace), "show", paper_id]) == 0
    assert json.loads(capsys.readouterr().out)["paper_id"] == paper_id
    assert main(["--workspace", str(workspace), "versions", paper_id]) == 0
    assert json.loads(capsys.readouterr().out)["versions"][0]["version_number"] == 1


def test_rest_import_query_and_metadata_conflict(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "paper.txt"
    source.write_text("body", encoding="utf-8")
    client = TestClient(create_app(EmptyService(), paper_workspace_roots=[tmp_path]))

    imported = client.post(
        "/v1/projects/demo/papers/import", json={"source_path": str(source)}
    )
    assert imported.status_code == 201
    body = imported.json()
    paper_id = body["paper"]["paper_id"]
    assert ".paperclaw" not in json.dumps(body)

    assert client.get("/v1/projects/demo/papers").json()["papers"][0]["paper_id"] == paper_id
    confirmed = client.patch(
        f"/v1/projects/demo/papers/{paper_id}/metadata",
        json={"expected_revision": 1, "title": "Confirmed"},
    )
    assert confirmed.status_code == 200
    stale = client.patch(
        f"/v1/projects/demo/papers/{paper_id}/metadata",
        json={"expected_revision": 1, "title": "Stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_revision"] == 2


def test_rest_rejects_source_outside_allowed_roots(tmp_path) -> None:
    workspace = _workspace(tmp_path / "allowed")
    outside = tmp_path / "outside.txt"
    outside.write_text("body", encoding="utf-8")
    client = TestClient(create_app(EmptyService(), paper_workspace_roots=[workspace]))
    response = client.post(
        "/v1/projects/demo/papers/import", json={"source_path": str(outside)}
    )
    assert response.status_code == 400
    assert str(outside) not in response.text
