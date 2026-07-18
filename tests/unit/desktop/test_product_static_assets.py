from __future__ import annotations

from importlib.resources import files


def _text(name: str) -> str:
    return files("paperclaw.desktop").joinpath("static", name).read_text(encoding="utf-8")


def test_index_loads_product_assets_without_inline_script() -> None:
    html = _text("index.html")
    assert '<link rel="stylesheet" href="product.css">' in html
    assert '<script src="product.js"></script>' in html
    assert 'id="product-panel"' in html
    assert 'id="product-nav"' in html
    assert 'id="refresh-project-index"' in html
    assert 'id="artifact-list"' in html
    assert "<script>" not in html
    assert "v0.30" in html


def test_product_javascript_uses_text_content_and_allowlisted_methods() -> None:
    script = _text("product.js")
    for method in (
        "get_product_overview",
        "get_capabilities",
        "get_project_status",
        "refresh_project_index",
        "list_artifacts",
        "get_artifact",
        "export_artifact",
    ):
        assert method in script
    assert ".innerHTML" not in script
    assert "textContent" in script
    assert "X-PaperClaw-Token" in script


def test_product_styles_are_responsive_and_theme_token_based() -> None:
    styles = _text("product.css")
    assert "var(--pc-card)" in styles
    assert "@media (max-width: 760px)" in styles
    assert ".product-panel[hidden]" in styles
