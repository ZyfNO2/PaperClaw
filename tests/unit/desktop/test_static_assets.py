from importlib.resources import files
import re


# DOM ids the live console, provider, product, and shell wiring depends on.
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
    "page-title",
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
    "console-cwd",
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
    "settings-title",
    "settings-page-title",
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
    # Workbench shell pages and overlays.
    "page-overview",
    "page-console",
    "page-missions",
    "page-project",
    "page-capabilities",
    "page-artifacts",
    "page-runs",
    "page-providers",
    "overview-root",
    "missions-root",
    "project-root",
    "capabilities-root",
    "artifacts-root",
    "runs-root",
    "providers-root",
    "inspector",
    "inspector-backdrop",
    "inspector-title",
    "inspector-body",
    "close-inspector",
    "modal-root",
    # Settings preferences controls.
    "pref-theme",
    "pref-language",
    "pref-density",
    "pref-motion",
    "pref-default-view",
    "pref-console-font",
    "pref-demo-mode",
    "pref-log-limit",
}


THEMES = {
    "dark",
    "light",
}


STYLE_FILES = (
    "styles/tokens.css",
    "styles/base.css",
    "styles/layout.css",
    "styles/components.css",
    "styles/pages.css",
    "styles/responsive.css",
)


MOCK_LAYER_FILES = ("js/mock-data.js", "js/shell.js", "js/pages.js")


def _asset(name: str) -> str:
    return (
        files("paperclaw.desktop").joinpath("static", name).read_text(encoding="utf-8")
    )


def test_static_assets_are_packaged_and_reference_only_local_resources() -> None:
    html = _asset("index.html")
    javascript = _asset("app.js")
    provider_css = _asset("provider-config.css")
    provider_javascript = _asset("provider-config.js")
    assert html.startswith("<!doctype html>")
    assert provider_css.strip()
    assert javascript.strip()
    assert provider_javascript.strip()
    for name in STYLE_FILES + MOCK_LAYER_FILES:
        assert _asset(name).strip(), f"{name} must be packaged and non-empty"
    assert not re.search(r"(?:src|href)=[\"']https?://", html, flags=re.IGNORECASE)
    for name in STYLE_FILES + ("provider-config.css",):
        assert "@import url(" not in _asset(name).lower()
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_html_has_expected_controls_and_security_policy() -> None:
    html = _asset("index.html")
    for element_id in EXPECTED_IDS:
        assert f'id="{element_id}"' in html
    assert "Content-Security-Policy" in html
    assert "connect-src 'self'" in html
    assert "connect-src 'none'" not in html
    assert "style-src 'self'" in html
    assert "unsafe-inline" not in html
    assert '<label class="sr-only" for="task">' in html
    assert 'aria-live="polite"' in html
    assert html.index('src="i18n.js"') < html.index('src="provider-config.js"')
    assert html.index('src="provider-config.js"') < html.index('src="app.js"')
    assert html.index('src="js/mock-data.js"') < html.index('src="app.js"')
    assert html.index('src="js/shell.js"') < html.index('src="app.js"')
    assert "Enable verification &amp; reflection gate" in html
    assert "v0.30" in html


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


def test_mock_layer_avoids_unsafe_execution_and_never_touches_the_bridge() -> None:
    for name in MOCK_LAYER_FILES:
        source = _asset(name).lower()
        for forbidden in (
            "sessionstorage",
            "document.cookie",
            "indexeddb",
            "eval(",
            "new function",
            ".innerhtml",
            "console.log",
            "xmlhttprequest",
        ):
            assert forbidden not in source, f"{forbidden} found in {name}"
        assert "pywebview" not in source
        assert "x-paperclaw-token" not in source
        assert not re.search(r"sk-[a-z0-9_-]{16,}", source, flags=re.IGNORECASE)
    # Mock data must stay data-only: no network and no credential-shaped keys.
    mock_source = _asset("js/mock-data.js")
    assert "fetch(" not in mock_source
    assert "api_key" not in mock_source
    # UI preferences live in one namespaced, non-secret localStorage record.
    shell_source = _asset("js/shell.js")
    assert "paperclaw.ui.v1" in shell_source
    assert "api_key" not in shell_source


def test_workbench_theme_set_and_dark_default_are_preserved() -> None:
    tokens = _asset("styles/tokens.css")
    html = _asset("index.html")
    for theme in THEMES:
        assert f'[data-theme="{theme}"]' in tokens
        assert f'value="{theme}"' in html
    assert '<html lang="zh-CN" data-theme="dark">' in html
    for token in (
        "--color-bg",
        "--color-surface-1",
        "--color-surface-2",
        "--color-surface-3",
        "--color-text",
        "--color-text-muted",
        "--color-border",
        "--color-primary",
        "--color-success",
        "--color-warning",
        "--color-danger",
        "--color-info",
        "--space-1",
        "--space-8",
        "--radius-sm",
        "--radius-md",
        "--radius-lg",
        "--shadow-sm",
        "--shadow-md",
    ):
        assert f"{token}:" in tokens
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
    base = _asset("styles/base.css")
    responsive = _asset("styles/responsive.css")
    provider_css = _asset("provider-config.css")
    assert "min-width: 360px" in base
    assert "@media (max-width: 1100px)" in responsive
    assert "@media (max-width: 768px)" in responsive
    assert "@media (max-width: 560px)" in responsive
    assert "grid-template-columns: minmax(0, 1fr)" in responsive
    assert "@media(max-width:720px)" in provider_css
    assert ".provider-form-grid" in provider_css
