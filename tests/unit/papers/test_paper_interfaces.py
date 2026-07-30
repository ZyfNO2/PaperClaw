from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

import fitz
from fastapi.testclient import TestClient

from paperclaw.academic import AcademicRuntime
from paperclaw.academic.fixtures import canonical_fixture_bytes
from paperclaw.papers.cli import main
from paperclaw.papers import PaperImportRequest, PaperService
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
    assert body["paper"]["schema_version"] == "academic.v1"
    assert body["paper"]["current_version"]["source_hash"]
    assert ".paperclaw" not in json.dumps(body)

    assert (
        client.get("/v1/projects/demo/papers").json()["papers"][0]["paper_id"]
        == paper_id
    )
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


def test_openapi_and_contract_endpoint_publish_academic_v1(tmp_path) -> None:
    client = TestClient(create_app(EmptyService(), paper_workspace_roots=[tmp_path]))
    contract = client.get("/v1/contracts/academic.v1")
    assert contract.status_code == 200
    assert len(contract.json()["oneOf"]) == 6
    openapi = client.get("/openapi.json").json()
    assert openapi["x-paperclaw-academic-contract"] == {
        "schema_version": "academic.v1",
        "schema_path": "/v1/contracts/academic.v1",
        "owner": "PaperClaw",
    }
    assert (
        openapi["paths"]["/v1/projects/{project_id}/academic/retrieve"]["post"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/AcademicV1Contract/$defs/evidence_bundle"
    )
    assert (
        openapi["components"]["schemas"]["EvidenceBundleWire"]["$ref"]
        == "#/components/schemas/AcademicV1Contract/$defs/evidence_bundle"
    )
    assert (
        openapi["paths"]["/v1/projects/{project_id}/academic/search"]["post"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/RetrievalResponseWire"
    )
    assert (
        openapi["paths"]["/v1/projects/{project_id}/academic/resolve"]["post"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/AcademicV1Contract/$defs/academic_object"
    )
    assert (
        openapi["paths"]["/v1/projects/{project_id}/papers/{paper_id}"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/AcademicV1Contract/$defs/paper_record"
    )
    assert (
        openapi["paths"]["/v1/projects/{project_id}/papers/{paper_id}/metadata"][
            "patch"
        ]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/AcademicV1Contract/$defs/paper_record"
    )


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


def test_rest_does_not_resolve_project_above_allowed_root(tmp_path) -> None:
    ProjectManifestStore(tmp_path).initialize("Parent")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "paper.txt"
    source.write_text("body", encoding="utf-8")
    client = TestClient(create_app(EmptyService(), paper_workspace_roots=[allowed]))
    response = client.post(
        "/v1/projects/parent/papers/import", json={"source_path": str(source)}
    )
    assert response.status_code == 400


def test_rest_parse_resolve_and_asset_readback_use_canonical_locator(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Stable locator evidence")
    document.save(source)
    document.close()
    client = TestClient(create_app(EmptyService(), paper_workspace_roots=[tmp_path]))

    imported = client.post(
        "/v1/projects/demo/papers/import", json={"source_path": str(source)}
    ).json()["paper"]
    paper_id = imported["paper_id"]
    parsed = client.post(f"/v1/projects/demo/papers/{paper_id}/parse")
    assert parsed.status_code == 200
    assert parsed.json()["schema_version"] == "academic.v1"

    runtime = AcademicRuntime.for_workspace(workspace, "demo")
    runtime.build_index()
    result = runtime.get_parse(paper_id, imported["current_version"]["version_id"])
    page_object = next(item for item in result.objects if item.object_type == "page")
    resolved = client.post(
        "/v1/projects/demo/academic/resolve",
        json={"locator": page_object.locator.to_dict()},
    )
    assert resolved.status_code == 200
    assert resolved.json()["object_id"] == page_object.object_id
    asset = page_object.assets[0]
    image = client.post(
        "/v1/projects/demo/academic/asset",
        json={
            "locator": page_object.locator.to_dict(),
            "asset_hash": asset.asset_hash,
        },
    )
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")

    searched = client.post(
        "/v1/projects/demo/academic/search",
        json={
            "query": "stable locator",
            "channels": ["lexical"],
            "paper_ids": [paper_id],
            "include_neighbors": True,
            "neighbor_count": 1,
            "include_assets": True,
            "max_asset_bytes": 1,
        },
    )
    assert searched.status_code == 200
    search_body = searched.json()
    assert search_body["bundle"]["schema_version"] == "academic.v1"
    assert search_body["hits"]
    assert search_body["assets_truncated"] is True
    assert search_body["asset_bytes_used"] == 0
    assert ".paperclaw" not in searched.text
    fixture = (
        Path(__file__).parents[2]
        / "fixtures"
        / "academic"
        / "retrieval_rest_success.v1.json"
    )
    fixture_response = client.post(
        "/v1/projects/demo/academic/search",
        json={
            "query": "stable locator",
            "channels": ["lexical"],
            "paper_ids": [paper_id],
        },
    )
    assert fixture_response.status_code == 200
    assert fixture_response.json()["index_metadata"]["schema_version"] == "academic.v1"
    assert (
        fixture_response.json()["index_metadata"]["generation_id"]
        == fixture_response.json()["bundle"]["trace"]["index_generation_id"]
    )
    actual_fixture = canonical_fixture_bytes(fixture_response.json())
    assert b'"index_metadata"' in actual_fixture
    if os.getenv("PAPERCLAW_UPDATE_ACADEMIC_FIXTURES") == "1":
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_bytes(actual_fixture)
    assert fixture.read_bytes() == actual_fixture
    inspected = client.get("/v1/projects/demo/academic/index")
    assert inspected.status_code == 200
    assert inspected.json()["index_version"] == "academic-object-index.v1"
    zero_hit = client.post(
        "/v1/projects/demo/academic/search",
        json={"query": "quantum banana unobtainium", "channels": ["lexical"]},
    )
    assert zero_hit.status_code == 200
    assert zero_hit.json()["bundle"]["candidates"] == []
    text_truncated = client.post(
        "/v1/projects/demo/academic/search",
        json={
            "query": "stable locator",
            "channels": ["lexical"],
            "max_chars": 5,
        },
    )
    assert text_truncated.status_code == 200
    assert text_truncated.json()["text_chars_used"] == 5
    assert text_truncated.json()["text_truncated"] is True

    with sqlite3.connect(runtime.database) as db:
        db.execute(
            """
            UPDATE academic_index_manifests SET index_version='stale.v0'
            WHERE generation_id=(SELECT generation_id FROM index_generations WHERE active=1)
            """
        )
    stale_index = client.get("/v1/projects/demo/academic/index")
    assert stale_index.status_code == 409
    assert stale_index.json()["detail"]["code"] == "academic_stale_index"
    with sqlite3.connect(runtime.database) as db:
        db.execute(
            """
            UPDATE academic_index_manifests
            SET index_version='academic-object-index.v1', content_hash=?
            WHERE generation_id=(SELECT generation_id FROM index_generations WHERE active=1)
            """,
            ("0" * 64,),
        )
    integrity = client.get("/v1/projects/demo/academic/index")
    assert integrity.status_code == 409
    assert integrity.json()["detail"]["code"] == "academic_integrity_failure"

    cases = {
        "success": fixture_response.json(),
        "zero_hit": zero_hit.json(),
        "resolve": resolved.json(),
        "index": inspected.json(),
        "stale_error": stale_index.json(),
        "integrity_error": integrity.json(),
        "asset_budget_truncation": search_body,
        "text_budget_truncation": text_truncated.json(),
        "asset_readback": {
            "asset_hash": asset.asset_hash,
            "content_sha256": asset.asset_hash,
            "content_type": image.headers["content-type"],
            "etag": image.headers["etag"],
            "byte_length": len(image.content),
        },
    }
    cases_fixture = (
        Path(__file__).parents[2]
        / "fixtures"
        / "academic"
        / "retrieval_rest_cases.v1.json"
    )
    cases_bytes = canonical_fixture_bytes(cases)
    if os.getenv("PAPERCLAW_UPDATE_ACADEMIC_FIXTURES") == "1":
        cases_fixture.write_bytes(cases_bytes)
    assert cases_fixture.read_bytes() == cases_bytes


def test_rest_exposes_conflict_driven_corrective_trace(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    papers = PaperService.for_workspace(workspace, project_id="demo")
    for name, text in (
        ("a.txt", "Results\nF1 is 91.2 percent dataset: Crack500 split: test"),
        ("b.txt", "Results\nF1 is 88.0 percent dataset: Crack500 split: test"),
    ):
        source = workspace / name
        source.write_text(text, encoding="utf-8")
        papers.import_paper(PaperImportRequest("demo", source))
    runtime = AcademicRuntime.for_workspace(workspace, "demo")
    for paper in papers.list_papers("demo"):
        runtime.parse_paper(paper.paper_id)
    runtime.build_index()
    client = TestClient(create_app(EmptyService(), paper_workspace_roots=[tmp_path]))

    response = client.post(
        "/v1/projects/demo/academic/search",
        json={"query": "F1", "channels": ["lexical"]},
    )

    assert response.status_code == 200
    trace = response.json()["bundle"]["trace"]
    assert trace["rounds_used"]["conflict"] == 1
    assert trace["stop_reason"] == "conflict_unresolved"
    assert (
        trace["corrective_details"]["original_conflicts"][0]["conflict_type"]
        == "metric_value"
    )
