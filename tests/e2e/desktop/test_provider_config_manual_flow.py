from __future__ import annotations

from playwright.sync_api import Page, expect

from conftest import install_bridge, load_app


def test_manual_model_override_and_return_to_env(page: Page) -> None:
    install_bridge(page)
    load_app(page)

    page.get_by_role("button", name="Settings", exact=False).click()
    page.locator("#provider-base-url").fill("https://manual.example/v1")
    page.locator("#provider-api-key").fill("temporary-secret")
    page.locator("#provider-connect").click()

    expect(page.locator("#provider-connect-status")).to_have_attribute(
        "data-state", "success"
    )
    expect(page.locator("#config-model")).to_contain_text("manual-model-a")
    assert page.evaluate("window.__bridgeCalls.providerConnect") == [
        {
            "base_url": "https://manual.example/v1",
            "api_key": "temporary-secret",
            "provider": "openai-compatible",
        }
    ]

    page.locator("#provider-manual-model").fill("unlisted-manual-model")
    page.locator("#use-manual-model").click()

    expect(page.locator("#config-model")).to_contain_text("unlisted-manual-model")
    expect(page.locator("#active-config-status")).to_contain_text("MANUAL")
    assert page.evaluate("window.__bridgeCalls.manual") == ["unlisted-manual-model"]

    page.locator("#disconnect-provider").click()

    expect(page.locator("#config-model")).to_have_text("env-model")
    expect(page.locator("#provider-summary")).to_contain_text("ENV")
    expect(page.locator("#disconnect-provider")).to_be_disabled()
    assert page.evaluate("window.__bridgeCalls.clear") == 1
