from __future__ import annotations

from playwright.sync_api import Page, expect

from conftest import install_bridge, load_app


def test_manual_model_override_and_return_to_env(page: Page) -> None:
    install_bridge(page)
    page.evaluate(
        """
        (() => {
          window.__bridgeCalls.manual = [];
          window.__bridgeCalls.clear = 0;
          window.pywebview.api.select_provider_model = async (model, allowUnlisted = false) => {
            if (allowUnlisted) window.__bridgeCalls.manual.push(model);
            else window.__bridgeCalls.models.push(model);
            return {
              ok: true,
              provider_source: 'manual',
              provider: 'openai-compatible',
              base_url: 'https://manual.example/v1',
              model,
              selected_model: model,
              models: [model, 'manual-model-a', 'manual-model-b'],
              configured: true,
              model_source: allowUnlisted ? 'manual' : 'discovered',
              model_verified: !allowUnlisted
            };
          };
          window.pywebview.api.clear_manual_provider = async () => {
            window.__bridgeCalls.clear += 1;
            return {
              ok: true,
              workspace: '/tmp/paperclaw-workspace',
              provider_source: 'env',
              provider: 'openai-compatible',
              base_url: 'https://provider.example/v1',
              model: 'env-model',
              models: ['env-model'],
              configured: true,
              missing: [],
              manual_provider_cleared: true
            };
          };
        })();
        """
    )
    load_app(page)

    page.get_by_role("button", name="Settings", exact=False).click()
    page.locator("#provider-base-url").fill("https://manual.example/v1")
    page.locator("#provider-api-key").fill("temporary-secret")
    page.locator("#connect-provider").click()
    expect(page.locator("#connection-status")).to_have_text("CONNECTED")

    page.locator("#provider-manual-model").fill("unlisted-manual-model")
    page.locator("#use-manual-model").click()

    expect(page.locator("#config-model")).to_have_text("unlisted-manual-model")
    expect(page.locator("#connection-status")).to_have_text("CONNECTED · MANUAL MODEL")
    expect(page.locator("#active-config-status")).to_contain_text("MANUAL")
    assert page.evaluate("window.__bridgeCalls.manual") == ["unlisted-manual-model"]

    page.locator("#disconnect-provider").click()

    expect(page.locator("#config-source")).to_have_text("Environment variables")
    expect(page.locator("#config-model")).to_have_text("env-model")
    expect(page.locator("#connection-status")).to_have_text("ENV READY")
    expect(page.locator("#provider-summary")).to_contain_text("ENV")
    expect(page.locator("#disconnect-provider")).to_be_disabled()
    assert page.evaluate("window.__bridgeCalls.clear") == 1
