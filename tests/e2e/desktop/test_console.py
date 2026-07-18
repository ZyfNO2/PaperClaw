from __future__ import annotations

from playwright.sync_api import Page, expect

from conftest import install_bridge, load_app


def test_shell_navigation_workspace_settings_and_sidebar_controls(page: Page) -> None:
    install_bridge(page)
    load_app(page)

    expect(page.locator("#provider-summary")).to_contain_text("ENV")
    expect(page.locator("#workspace-path")).to_have_text("/tmp/paperclaw-workspace")
    expect(page.locator("#config-credential")).to_have_text("Configured (hidden)")

    page.get_by_role("button", name="Settings", exact=False).click()
    expect(page.locator("#settings-panel")).to_be_visible()
    page.locator("#close-settings").click()
    expect(page.locator("#settings-panel")).to_be_hidden()

    page.locator('#sidebar-nav [data-nav="trace"]').click()
    expect(page.locator("#toast")).to_be_visible()
    expect(page.locator("#toast-message")).to_contain_text("under development")
    page.locator("#close-toast").click()

    page.locator("#workspace-card").click()
    expect(page.locator("#workspace-path")).to_have_text("/tmp/selected-workspace")
    assert page.evaluate("window.__bridgeCalls.select") == 1

    page.locator("#sidebar-toggle").click()
    expect(page.locator("#app")).to_have_class("sidebar-collapsed")
    page.locator("#sidebar-toggle").click()
    expect(page.locator("#app")).not_to_have_class("sidebar-collapsed")


def test_theme_switch_persists_and_browser_mode_receives_selected_theme(
    page: Page,
) -> None:
    install_bridge(page)
    load_app(page)

    expect(page.locator("html")).to_have_attribute("data-theme", "neo-brutalist")
    page.locator("#theme-select").select_option("terminal-dark")
    expect(page.locator("html")).to_have_attribute("data-theme", "terminal-dark")
    expect(page.locator("#toast-message")).to_contain_text("Terminal Dark")
    assert page.evaluate("window.__bridgeCalls.themes") == ["terminal-dark"]

    page.locator("#open-browser").click()
    expect(page.locator("#toast-message")).to_contain_text("Browser mode opened")
    assert page.evaluate("window.__bridgeCalls.browser") == ["terminal-dark"]


def test_execute_flow_uses_env_payload_and_renders_events_and_result(
    page: Page,
) -> None:
    install_bridge(page)
    load_app(page)

    page.locator("#task").fill("创建 hello.py 并运行验证")
    page.locator("#send-button").click()

    expect(page.locator("#task")).to_have_value("")
    expect(page.locator("#run-status")).to_have_text("COMPLETED", timeout=5000)
    expect(page.locator("#run-subtitle")).to_contain_text("run-e2e")
    expect(page.locator("#model-calls")).to_have_text("1")
    expect(page.locator("#tool-calls")).to_have_text("1")
    expect(page.locator("#verification-status")).to_have_text("PASSED")
    expect(page.locator("#mission-log")).to_contain_text(
        "任务完成：hello.py 已创建并验证。"
    )
    expect(page.locator("#timeline .event-row")).to_have_count(4)

    payload = page.evaluate("window.__bridgeCalls.start[0]")
    assert payload == {
        "task": "创建 hello.py 并运行验证",
        "workspace": "/tmp/paperclaw-workspace",
        "enable_verification_gate": True,
        "max_steps": 12,
        "max_model_calls": 10,
        "max_tool_calls": 20,
    }
    assert "api_key" not in payload
    assert "base_url" not in payload
    assert "model" not in payload

    page.locator('[data-tl-filter="tool"]').click()
    expect(page.locator('#timeline .event-row[data-type="tool"]')).to_be_visible()
    expect(page.locator('#timeline .event-row[data-type="model"]')).to_be_hidden()
    page.locator('[data-tl-filter="all"]').click()
    expect(page.locator('#timeline .event-row[data-type="model"]')).to_be_visible()


def test_cancel_flow_disables_duplicate_submission_and_reaches_terminal_state(
    page: Page,
) -> None:
    install_bridge(page, auto_complete=False)
    load_app(page)

    page.locator("#task").fill("运行一个长任务")
    page.locator("#run-button").click()
    expect(page.locator("#run-button")).to_be_disabled()
    expect(page.locator("#cancel-button")).to_be_enabled()

    page.locator("#cancel-button").click()
    expect(page.locator("#run-status")).to_have_text("CANCELLED", timeout=5000)
    expect(page.locator("#cancel-button")).to_be_disabled()
    expect(page.locator("#run-button")).to_be_enabled()
    assert page.evaluate("window.__bridgeCalls.cancel") == 1
    assert len(page.evaluate("window.__bridgeCalls.start")) == 1


def test_validation_shortcuts_search_new_run_and_trace_export(page: Page) -> None:
    install_bridge(page)
    load_app(page)

    page.locator("#send-button").click()
    expect(page.locator("#public-error")).to_contain_text("validation_error")

    page.locator('[data-insert="/file "]').click()
    expect(page.locator("#task")).to_have_value("/file ")
    page.locator("#clear-task").click()
    expect(page.locator("#task")).to_have_value("")

    page.locator("#task").fill("通过 Enter 执行")
    page.locator("#task").press("Enter")
    expect(page.locator("#run-status")).to_have_text("COMPLETED", timeout=5000)

    page.locator("#global-search").fill("hello.py")
    expect(page.locator("#mission-log .msg-agent")).to_be_visible()
    page.locator("#global-search").fill("不存在的内容")
    expect(page.locator("#mission-log .msg-agent")).not_to_be_visible()
    page.locator("#global-search").fill("")

    with page.expect_download() as download_info:
        page.locator("#export-button").click()
    assert download_info.value.suggested_filename == "run-e2e.json"

    page.locator("#new-run-button").click()
    expect(page.locator("#timeline .event-row")).to_have_count(0)
    expect(page.locator("#run-subtitle")).to_contain_text("not-started")
