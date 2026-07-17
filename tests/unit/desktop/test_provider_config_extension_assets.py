from importlib.resources import files


def _asset(name: str) -> str:
    return files("paperclaw.desktop").joinpath("static", name).read_text(encoding="utf-8")


def test_extended_provider_controls_are_packaged() -> None:
    html = _asset("index.html")
    javascript = _asset("app.js")

    for element_id in (
        "provider-manual-model",
        "use-manual-model",
        "disconnect-provider",
        "active-config-status",
    ):
        assert f'id="{element_id}"' in html

    assert "api.select_provider_model(selected, true)" in javascript
    assert "api.clear_manual_provider()" in javascript
    assert "Previous provider remains active" in javascript


def test_extended_provider_controls_do_not_persist_credentials() -> None:
    combined = "\n".join((_asset("index.html"), _asset("app.js"))).lower()
    for forbidden in (
        "localstorage",
        "sessionstorage",
        "document.cookie",
        "indexeddb",
        "console.log",
        "fetch(",
        "xmlhttprequest",
    ):
        assert forbidden not in combined
    assert combined.count("api_key") == 1
