"""Frozen 12 locator contract tests — requires local data/paper_corpus.

Marked as corpus_acceptance; excluded from CI (no PDFs in remote).
Run locally: pytest -m corpus_acceptance tests/acceptance/test_frozen_12_locators.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from paperclaw.academic import AcademicRuntime
from paperclaw.papers import PaperImportRequest, PaperService
from paperclaw.projects import ProjectManifestStore

pytestmark = pytest.mark.corpus_acceptance

FROZEN_PATH = Path("benchmarks/academic_rag/v1/frozen_12.json")
CORPUS_ROOT = Path("data/paper_corpus")


@pytest.fixture(scope="module")
def frozen_set():
    if not FROZEN_PATH.exists():
        pytest.skip("frozen_12.json not found")
    return json.loads(FROZEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus_pdfs():
    if not CORPUS_ROOT.exists():
        pytest.skip("data/paper_corpus not found")
    return {p.name: p for p in CORPUS_ROOT.rglob("*.pdf")}


@pytest.fixture(scope="module")
def runtime_and_papers(tmp_path_factory, frozen_set, corpus_pdfs):
    workspace = tmp_path_factory.mktemp("frozen12")
    manifest = ProjectManifestStore(workspace).initialize("Frozen 12 acceptance")
    papers = PaperService.for_workspace(workspace, project_id=manifest.project_id)
    runtime = AcademicRuntime(workspace, manifest.project_id)

    entry_map = {}
    manifest_lines = Path(
        "benchmarks/academic_rag/v1/corpus_manifest.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    for line in manifest_lines:
        entry = json.loads(line)
        entry_map[entry["entry_id"]] = entry

    imported = {}
    for paper in frozen_set["papers"]:
        entry = entry_map[paper["entry_id"]]
        pdf_path = None
        for name, path in corpus_pdfs.items():
            if name == entry["logical_filename"]:
                pdf_path = path
                break
        if pdf_path is None:
            pytest.skip(f"PDF not found: {entry['logical_filename']}")
        result = papers.import_paper(
            PaperImportRequest(manifest.project_id, pdf_path)
        )
        imported[paper["blind_id"]] = (result.paper.paper_id, entry)
    return runtime, papers, imported, manifest.project_id


def test_all_frozen_papers_parse_to_ready_or_partial(
    runtime_and_papers,
):
    runtime, _, imported, _ = runtime_and_papers
    for blind_id, (paper_id, entry) in imported.items():
        result = runtime.parse_paper(paper_id)
        assert result.status in ("ready", "partial"), (
            f"{blind_id} ({entry['logical_filename']}): status={result.status}"
        )


def test_all_objects_have_valid_page_number(runtime_and_papers):
    runtime, _, imported, _ = runtime_and_papers
    for blind_id, (paper_id, _) in imported.items():
        result = runtime.parse_paper(paper_id)
        for obj in result.objects:
            assert obj.locator.page_number >= 1, (
                f"{blind_id} object {obj.object_id}: page_number < 1"
            )


def test_pdf_objects_have_bounding_box(runtime_and_papers):
    runtime, _, imported, _ = runtime_and_papers
    for blind_id, (paper_id, _) in imported.items():
        result = runtime.parse_paper(paper_id)
        for obj in result.objects:
            if obj.object_type == "document":
                continue
            assert obj.locator.bounding_box is not None, (
                f"{blind_id} object {obj.object_id}: missing bounding_box"
            )


def test_table_cells_have_row_and_column(runtime_and_papers):
    runtime, _, imported, _ = runtime_and_papers
    for blind_id, (paper_id, _) in imported.items():
        result = runtime.parse_paper(paper_id)
        for obj in result.objects:
            if obj.object_type == "table_cell":
                assert obj.locator.table_row is not None, (
                    f"{blind_id} cell {obj.object_id}: missing table_row"
                )
                assert obj.locator.table_column is not None, (
                    f"{blind_id} cell {obj.object_id}: missing table_column"
                )


def test_diverse_object_types_across_corpus(runtime_and_papers):
    runtime, _, imported, _ = runtime_and_papers
    all_types: set[str] = set()
    for _, (paper_id, _) in imported.items():
        result = runtime.parse_paper(paper_id)
        all_types.update(obj.object_type for obj in result.objects)
    for expected in ("equation", "caption", "table", "figure", "section"):
        assert expected in all_types, f"object type '{expected}' not found in corpus"


def test_resolve_succeeds_for_all_objects(runtime_and_papers):
    runtime, _, imported, _ = runtime_and_papers
    for blind_id, (paper_id, _) in imported.items():
        result = runtime.parse_paper(paper_id)
        for obj in result.objects:
            resolved = runtime.resolve(obj.locator)
            assert resolved.object_id == obj.object_id


def test_parse_is_idempotent(runtime_and_papers):
    runtime, _, imported, _ = runtime_and_papers
    for blind_id, (paper_id, _) in imported.items():
        first = runtime.parse_paper(paper_id)
        second = runtime.parse_paper(paper_id)
        assert first.manifest_id == second.manifest_id, (
            f"{blind_id}: parse not idempotent"
        )
        assert len(first.objects) == len(second.objects)
