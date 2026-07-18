from __future__ import annotations

import importlib
from importlib.resources import files

from paperclaw.desktop import app
from paperclaw.desktop.i18n import install_i18n_extension


def test_i18n_asset_is_packaged_and_loaded_before_ui_scripts() -> None:
    static = files("paperclaw.desktop").joinpath("static")
    html = static.joinpath("index.html").read_text(encoding="utf-8")
    javascript = static.joinpath("i18n.js").read_text(encoding="utf-8")

    assert static.joinpath("i18n.js").is_file()
    assert html.index('src="i18n.js"') < html.index('src="provider-config.js"')
    assert html.index('src="i18n.js"') < html.index('src="app.js"')
    assert 'id="language-select"' in html
    assert 'value="zh-CN"' in html
    assert 'value="en"' in html
    assert "paperclaw.locale.v1" in javascript
    assert "paperclaw:locale-changed" in javascript
    assert "DYNAMIC_IDS" in javascript


def test_i18n_browser_asset_registration_is_idempotent() -> None:
    original = dict(app._BROWSER_ASSETS)
    marker = "_paperclaw_i18n_extension_installed"
    try:
        if hasattr(app, marker):
            delattr(app, marker)
        app._BROWSER_ASSETS.pop("/i18n.js", None)

        install_i18n_extension(app)
        installed = app._BROWSER_ASSETS["/i18n.js"]
        install_i18n_extension(app)

        assert installed == ("i18n.js", "text/javascript; charset=utf-8")
        assert app._BROWSER_ASSETS["/i18n.js"] == installed
    finally:
        app._BROWSER_ASSETS.clear()
        app._BROWSER_ASSETS.update(original)
        if hasattr(app, marker):
            delattr(app, marker)
        import paperclaw.desktop.bootstrap as bootstrap

        importlib.reload(bootstrap)
