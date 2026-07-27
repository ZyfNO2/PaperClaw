from paperclaw.desktop.product_service import DesktopProductService
from paperclaw.desktop.contracts import DesktopPublicError
from paperclaw.projects import ProjectManifestStore
import pytest
import fitz


def test_desktop_paper_flow_reuses_domain_service(tmp_path) -> None:
    ProjectManifestStore(tmp_path).initialize("Demo")
    source = tmp_path / "论文 evidence.txt"
    source.write_text("body", encoding="utf-8")
    service = DesktopProductService()
    imported = service.import_paper(str(tmp_path), str(source))
    paper_id = imported["result"]["paper"]["paper_id"]
    assert imported["ok"] and ".paperclaw" not in str(imported)
    assert service.list_papers(str(tmp_path))["papers"][0]["paper_id"] == paper_id
    assert service.get_paper(str(tmp_path), paper_id)["paper"]["paper_id"] == paper_id
    assert service.list_paper_versions(str(tmp_path), paper_id)["versions"][0]["version_number"] == 1
    confirmed = service.confirm_paper_metadata(
        str(tmp_path), paper_id, {"title": "已确认标题"}, 1
    )
    assert confirmed["paper"]["metadata"]["title"]["status"] == "confirmed"

    with pytest.raises(DesktopPublicError, match="year"):
        service.confirm_paper_metadata(str(tmp_path), paper_id, {"year": 3.5}, 2)


def test_desktop_academic_parse_index_and_retrieve(tmp_path) -> None:
    ProjectManifestStore(tmp_path).initialize("Demo")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "1 Findings", fontsize=18)
    page.insert_text((72, 110), "Crack width evidence is 0.4 mm.")
    source = tmp_path / "paper.pdf"
    document.save(source)
    document.close()
    service = DesktopProductService()
    imported = service.import_paper(str(tmp_path), str(source))
    paper_id = imported["result"]["paper"]["paper_id"]
    parsed = service.parse_academic_paper(str(tmp_path), paper_id)
    assert parsed["parse"]["page_count"] == 1
    assert service.build_academic_index(str(tmp_path))["index"]["state"] == "ready"
    result = service.retrieve_academic(str(tmp_path), "crack width")
    assert result["result"]["candidates"][0]["locator"]["paper_id"] == paper_id
