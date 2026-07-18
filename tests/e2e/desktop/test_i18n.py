from __future__ import annotations

from playwright.sync_api import Page, expect

from conftest import install_bridge, load_app


def test_language_switch_updates_static_text_and_preserves_runtime_state(page: Page) -> None:
    install_bridge(page)
    load_app(page)

    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator("h1.title")).to_have_text("CONSOLE")
    expect(page.locator("#workspace-path")).to_have_text("/tmp/paperclaw-workspace")

    page.locator("#language-select").select_option("zh-CN")

    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    expect(page.locator("h1.title")).to_have_text("控制台")
    expect(page.locator("#run-button")).to_contain_text("执行")
    expect(page.locator("#task")).to_have_attribute("placeholder", "输入指令或使用 / 命令…")
    expect(page.locator("#workspace-path")).to_have_text("/tmp/paperclaw-workspace")
    assert page.evaluate("window.PaperClawI18n.getLocale()") == "zh-CN"

    page.locator("#language-select").select_option("en")

    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator("h1.title")).to_have_text("CONSOLE")
    expect(page.locator("#run-button")).to_contain_text("EXECUTE")
    expect(page.locator("#workspace-path")).to_have_text("/tmp/paperclaw-workspace")


def test_dynamic_messages_follow_selected_language(page: Page) -> None:
    install_bridge(page)
    load_app(page)
    page.locator("#language-select").select_option("zh-CN")

    page.locator("#workspace-card").click()
    expect(page.locator("#toast-message")).to_have_text("工作区已更新。")

    page.locator("#theme-select").select_option("terminal-dark")
    expect(page.locator("#toast-message")).to_contain_text("主题：")

    page.locator("#language-select").select_option("en")
    expect(page.locator("#toast-message")).to_contain_text("Theme:")
