from paperclaw.desktop.product_service import DesktopProductService
from paperclaw.desktop.contracts import DesktopPublicError
from paperclaw.projects import ProjectManifestStore
import pytest


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
