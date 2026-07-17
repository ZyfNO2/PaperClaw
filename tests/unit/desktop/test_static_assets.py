from importlib.resources import files
import re


EXPECTED_IDS = {
    "provider",
    "base-url",
    "api-key",
    "toggle-key",
    "model",
    "workspace",
    "select-workspace",
    "verification-enabled",
    "max-steps",
    "max-model-calls",
    "max-tool-calls",
    "task",
    "task-count",
    "clear-task",
    "run-button",
    "cancel-button",
    "run-status",
    "summary-status",
    "model-calls",
    "tool-calls",
    "last-sequence",
    "verification-status",
    "verification-summary",
    "timeline",
    "final-result",
    "public-error",
    "global-search",
    "run-id-label",
    "workspace-label",
    "provider-label",
    "model-label",
    "under-develop-toast",
    "under-develop-message",
    "close-toast",
}

PLANNED_SURFACES = {
    "Runs",
    "Workspaces",
    "Trace Explorer",
    "Agent Management",
    "Knowledge Base",
    "Prompt Library",
    "Evaluation Dashboard",
    "Model Registry",
    "Settings",
    "Saved Provider Profiles",
    "Credential Vault",
    "Model Discovery",
    "Session Search",
    "Interactive Trace Graph",
    "File Preview",
    "Citation Inspector",
    "Markdown Preview",
    "Structured JSON Preview",
    "Result Diff",
    "Token Analytics",
    "Tool Usage Analytics",
    "Diagnostics Center",
}


def _asset(name: str) -> str:
    return files("paperclaw.desktop").joinpath("static", name).read_text(encoding="utf-8")


def test_static_assets_are_packaged_and_reference_only_local_resources() -> None:
    html = _asset("index.html")
    css = _asset("styles.css")
    javascript = _asset("app.js")
    assert html.startswith("<!doctype html>")
    assert css.strip()
    assert javascript.strip()
    assert not re.search(r"(?:src|href)=[\"']https?://", html, flags=re.IGNORECASE)
    assert "@import url(" not in css.lower()


def test_html_has_expected_controls_labels_and_security_policy() -> None:
    html = _asset("index.html")
    for element_id in EXPECTED_IDS:
        assert f'id="{element_id}"' in html
    assert "Content-Security-Policy" in html
    assert "connect-src 'none'" in html
    assert '<label for="api-key">' in html
    assert '<label class="sr-only" for="task">' in html
    assert 'aria-live="polite"' in html


def test_expanded_shell_exposes_planned_surfaces_as_under_develop_controls() -> None:
    html = _asset("index.html")
    javascript = _asset("app.js")
    for surface in PLANNED_SURFACES:
        assert f'data-under-develop="{surface}"' in html
    assert html.count("data-under-develop=") >= 45
    assert "Under Develop" in javascript
    assert "bindPlannedControls" in javascript
    assert "showUnderDevelop" in javascript
    assert "preventDefault" in javascript


def test_frontend_uses_no_persistence_remote_code_or_unsafe_dynamic_execution() -> None:
    combined = "\n".join((_asset("index.html"), _asset("app.js"))).lower()
    for forbidden in (
        "localstorage",
        "sessionstorage",
        "document.cookie",
        "indexeddb",
        "eval(",
        "new function",
        ".innerhtml",
    ):
        assert forbidden not in combined
    assert "console.log" not in combined
    assert "api_key" in combined
    assert 'payload.api_key = ""' in combined
    assert not re.search(r"sk-[a-z0-9_-]{16,}", combined, flags=re.IGNORECASE)


def test_styles_keep_controls_visible_in_narrow_layout() -> None:
    css = _asset("styles.css")
    assert "@media (max-width: 520px)" in css
    assert ".action-row" in css
    assert "flex-direction: column" in css
    assert "min-width: 360px" in css
    assert ".desktop-layout" in css
    assert ".sidebar" in css
    assert ".toast" in css
