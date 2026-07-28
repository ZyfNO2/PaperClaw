"""Parser idempotency and version replay tests using synthetic PDFs."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

fitz = pytest.importorskip("fitz")

from paperclaw.academic import AcademicRuntime  # noqa: E402
from paperclaw.papers import PaperImportRequest, PaperService  # noqa: E402
from paperclaw.projects import ProjectManifestStore  # noqa: E402


def _make_pdf(tmp_path: Path, text: str = "Hello World") -> Path:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 50), text, fontsize=12)
    page.insert_text((50, 100), "1. Introduction", fontsize=14)
    page.insert_text((50, 130), "Some paragraph text here.", fontsize=11)
    path = tmp_path / "synthetic.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def workspace(tmp_path: Path) -> tuple[Path, AcademicRuntime, PaperService, str]:
    manifest = ProjectManifestStore(tmp_path).initialize("Idempotency test")
    papers = PaperService.for_workspace(tmp_path, project_id=manifest.project_id)
    runtime = AcademicRuntime(tmp_path, manifest.project_id)
    return tmp_path, runtime, papers, manifest.project_id


def test_parse_twice_produces_same_manifest(workspace: tuple) -> None:
    tmp_path, runtime, papers, project_id = workspace
    pdf = _make_pdf(tmp_path)
    imported = papers.import_paper(PaperImportRequest(project_id, pdf))
    paper_id = imported.paper.paper_id
    first = runtime.parse_paper(paper_id)
    second = runtime.parse_paper(paper_id)
    assert first.manifest_id == second.manifest_id
    assert first.parser_fingerprint == second.parser_fingerprint
    assert len(first.objects) == len(second.objects)
    for a, b in zip(first.objects, second.objects, strict=True):
        assert a.object_id == b.object_id
        assert a.object_type == b.object_type
        assert a.text == b.text


def test_index_generation_is_idempotent(workspace: tuple) -> None:
    tmp_path, runtime, papers, project_id = workspace
    pdf = _make_pdf(tmp_path)
    imported = papers.import_paper(PaperImportRequest(project_id, pdf))
    runtime.parse_paper(imported.paper.paper_id)
    gen1 = runtime.build_index()
    gen2 = runtime.build_index()
    assert gen1.generation_id == gen2.generation_id
    assert gen1.state == "ready"


def test_old_version_locator_fails_after_new_version(workspace: tuple) -> None:
    tmp_path, runtime, papers, project_id = workspace
    pdf_v1 = _make_pdf(tmp_path, "Version one content")
    imported = papers.import_paper(PaperImportRequest(project_id, pdf_v1))
    paper_id = imported.paper.paper_id
    result_v1 = runtime.parse_paper(paper_id)
    v1_objects = result_v1.objects

    pdf_v2 = tmp_path / "synthetic_v2.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 50), "Version two completely different", fontsize=12)
    doc.save(str(pdf_v2))
    doc.close()
    papers.import_paper(PaperImportRequest(project_id, pdf_v2, paper_id=paper_id))

    result_v2 = runtime.parse_paper(paper_id)
    assert result_v2.manifest_id != result_v1.manifest_id

    v1_non_doc = [o for o in v1_objects if o.object_type != "document"]
    if v1_non_doc:
        with pytest.raises(KeyError):
            runtime.resolve(v1_non_doc[0].locator)


def test_markdown_parser_produces_sections_and_paragraphs(
    workspace: tuple,
) -> None:
    tmp_path, runtime, papers, project_id = workspace
    md = tmp_path / "paper.md"
    md.write_text(
        "# Introduction\n\nSome text.\n\n## Method\n\nMore text.\n\n```\ncode\n```\n",
        encoding="utf-8",
    )
    imported = papers.import_paper(PaperImportRequest(project_id, md))
    result = runtime.parse_paper(imported.paper.paper_id)
    types = {o.object_type for o in result.objects}
    assert "section" in types
    assert "paragraph" in types
    assert "algorithm" in types
    paragraphs = [item for item in result.objects if item.object_type == "paragraph"]
    assert all(
        item.locator.line_range is not None
        and item.locator.line_range[1] >= item.locator.line_range[0]
        for item in paragraphs
    )
    assert result.status == "ready"


def test_latex_parser_produces_structured_objects(workspace: tuple) -> None:
    tmp_path, runtime, papers, project_id = workspace
    tex = tmp_path / "paper.tex"
    tex.write_text(
        r"""\documentclass{article}
\begin{document}
\section{Introduction}
Hello world.
\begin{equation}
E = mc^2
\end{equation}
\begin{figure}
\caption{A figure}
\end{figure}
\begin{table}
\caption{A table}
\end{table}
See \cite{ref1}.
\bibitem{ref1} Author 2020
\end{document}
""",
        encoding="utf-8",
    )
    imported = papers.import_paper(PaperImportRequest(project_id, tex))
    result = runtime.parse_paper(imported.paper.paper_id)
    types = {o.object_type for o in result.objects}
    assert "section" in types
    assert "equation" in types
    assert "figure" in types
    assert "table" in types
    assert "reference" in types
    assert "citation" in types
    assert [item.reading_order for item in result.objects] == sorted(
        item.reading_order for item in result.objects
    )
    equation = next(item for item in result.objects if item.object_type == "equation")
    assert equation.locator.section_path == ("Introduction",)
    assert result.status == "ready"


def test_text_parser_produces_paragraphs(workspace: tuple) -> None:
    tmp_path, runtime, papers, project_id = workspace
    txt = tmp_path / "notes.txt"
    txt.write_text("1 Introduction\n\nSome body text.\n\n2 Method\n\nMore.\n", encoding="utf-8")
    imported = papers.import_paper(PaperImportRequest(project_id, txt))
    result = runtime.parse_paper(imported.paper.paper_id)
    types = {o.object_type for o in result.objects}
    assert "paragraph" in types
    assert result.status == "ready"


def test_docling_adapter_normalizes_items_and_keeps_page_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paperclaw.academic.parsers.docling_parser import DoclingParser

    pdf = _make_pdf(tmp_path)
    content = pdf.read_bytes()

    class FakeDocumentStream:
        def __init__(self, **values):
            self.values = values

    class FakeBox:
        l = 40.0  # noqa: E741 - mirrors Docling's bounding-box API
        t = 40.0
        r = 220.0
        b = 80.0

        def to_top_left_origin(self, *, page_height):
            assert page_height == 300.0
            return self

    item = SimpleNamespace(
        label="section_header",
        text="Introduction",
        prov=(SimpleNamespace(page_no=1, bbox=FakeBox()),),
    )
    fake_document = SimpleNamespace(
        pages={1: SimpleNamespace(size=SimpleNamespace(height=300.0))},
        iterate_items=lambda: iter(((item, 1),)),
    )

    class FakeConverter:
        def convert(self, source):
            assert source.values["name"] == "paper.pdf"
            return SimpleNamespace(document=fake_document)

    docling = ModuleType("docling")
    datamodel = ModuleType("docling.datamodel")
    base_models = ModuleType("docling.datamodel.base_models")
    converter = ModuleType("docling.document_converter")
    base_models.DocumentStream = FakeDocumentStream
    converter.DocumentConverter = FakeConverter
    monkeypatch.setitem(sys.modules, "docling", docling)
    monkeypatch.setitem(sys.modules, "docling.datamodel", datamodel)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter)

    result = DoclingParser().parse(
        content,
        "pdf",
        paper_id="paper-1",
        version_id="version-1",
        source_hash="a" * 64,
        asset_dir=tmp_path / "assets",
    )
    section = next(value for value in result.objects if value.object_type == "section")
    page = next(value for value in result.objects if value.object_type == "page")
    assert section.locator.bounding_box is not None
    assert section.locator.section_path == ("Introduction",)
    assert page.assets and page.assets[0].kind == "page"
