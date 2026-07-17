from importlib.resources import files
import re


EXPECTED_IDS = {
    "app",
    "sidebar",
    "sidebar-toggle",
    "workspace-card",
    "workspace-name",
    "workspace-path",
    "sidebar-nav",
    "trace-count",
    "env-badge",
    "new-run-button",
    "run-subtitle",
    "global-search",
    "run-status",
    "run-button",
    "cancel-button",
    "export-button",
    "select-workspace",
    "theme-select",
    "open-browser",
    "provider-summary",
    "mission-filters",
    "mission-log",
    "public-error",
    "task",
    "send-button",
    "clear-task",
    "task-count",
    "summary-status",
    "model-calls",
    "tool-calls",
    "last-sequence",
    "event-meta",
    "model-label",
    "verification-status",
    "verification-summary",
    "progress-label",
    "progress-bar",
    "timeline-filters",
    "timeline",
    "settings-panel",
    "close-settings",
    "config-source",
    "config-provider",
    "config-base-url",
    "config-model",
    "config-credential",
    "provider-connect-title",
    "provider-base-url",
    "provider-api-key",
    "provider-key-toggle",
    "provider-connect",
    "provider-model",
    "provider-reset",
    "provider-connect-status",
    "max-steps",
    "max-model-calls",
    "max-tool-calls",
    "verification-enabled",
    "gate-mode-status",
    "toast",
    "toast-message",
    "close-toast",
}


THEMES = {
    "neo-brutalist",
    "soft-minimal",
    "terminal-dark",
    "clean-mono",
    "paper-light",
}


def _asset(name: str) -> str:
    return (
        files("paperclaw.desktop").joinpath("static", name).read_text(encoding="utf-8")
    )


def test_static_assets_are_packaged_and_reference_only_local_resources() -> None:
    html = _asset("index.html")
    css = _asset("styles.css")
    provider_css = _asset("provider-config.css")
    javascript = _asset("app.js")
    provider_javascript = _asset("provider-config.js")
    assert html.startswith("<!doctype html>")
    assert css.strip()
    assert provider_css.strip()
    assert javascript.strip()
    assert provider_javascript.strip()
    assert not re.search(r"(?:src|href)=[\"']https?://", html, flags=re.IGNORECASE)
    assert "@import url(" not in css.lower()
    assert "@import url(" not in provider_css.lower()


def test_html_has_expected_controls_and_security_policy() -> None:
    html = _asset("index.html")
    for element_id in EXPECTED_IDS:
        assert f'id="{element_id}"' in html
    assert "Content-Security-Policy" in html
    assert "connect-src 'self'" in html
    assert "connect-src 'none'" not in html
    assert '<label class="sr-only" for="task">' in html
    assert 'aria-live="polite"' in html
    assert html.index('src="provider-config.js"') < html.index('src="app.js"')
    assert "Enable verification &amp; reflection gate" in html


def test_frontend_persists_only_non_secret_theme_state_and_avoids_unsafe_execution() -> (
    None
):
    html = _asset("index.html").lower()
    javascript = _asset("app.js").lower()
    provider_javascript = _asset("provider-config.js").lower()
    combined = "\n".join((html, javascript, provider_javascript))
    for forbidden in (
        "sessionstorage",
        "document.cookie",
        "indexeddb",
        "eval(",
        "new function",
        ".innerhtml",
    ):
        assert forbidden not in combined
    assert 'id="api-key"' not in html
    assert "api_key" not in javascript
    assert "paperclaw_api_key" not in combined
    assert "console.log" not in combined
    assert not re.search(r"sk-[a-z0-9_-]{16,}", combined, flags=re.IGNORECASE)
    assert 'const theme_storage_key = "paperclaw.theme.v1"' in javascript
    assert "localstorage.setitem(theme_storage_key" in javascript
    assert javascript.count("localstorage.setitem(") == 1
    assert "localstorage" not in provider_javascript
    assert 'ui.providerapikey.value = ""' in provider_javascript


def test_uploaded_theme_set_and_neobrutalist_default_are_preserved() -> None:
    css = _asset("styles.css")
    html = _asset("index.html")
    for theme in THEMES:
        assert f'[data-theme="{theme}"]' in css
        assert f'value="{theme}"' in html
    assert '<html lang="zh-CN" data-theme="neo-brutalist">' in html
    assert "--pc-background: #c5c9c9" in css
    assert "--pc-accent: #0040ff" in css
    assert "box-shadow:var(--pc-shadow" in css
    assert "MISSION LOG" in html
    assert "EVENT TIMELINE" in html
    assert "RUN STATUS" in html


def test_browser_transport_is_loopback_token_aware_and_provider_secret_safe() -> None:
    javascript = _asset("app.js")
    provider_javascript = _asset("provider-config.js")
    assert '"X-PaperClaw-Token"' in javascript
    assert "window.fetch(`/api/${method}`" in javascript
    assert "open_in_browser(currentTheme)" in javascript
    assert "api_key" not in javascript.lower()
    assert '"X-PaperClaw-Token"' in provider_javascript
    assert 'invoke("connect_provider"' in provider_javascript
    assert 'invoke("select_provider_model"' in provider_javascript
    assert "localstorage" not in provider_javascript.lower()


def test_styles_keep_controls_visible_in_narrow_layout() -> None:
    css = _asset("styles.css")
    provider_css = _asset("provider-config.css")
    assert "@media(max-width:720px)" in css
    assert "min-width:360px" in css
    assert ".toolbar-group" in css
    assert "flex-direction:column" in css
    assert "@media(max-width:720px)" in provider_css
    assert ".provider-form-grid" in provider_css
