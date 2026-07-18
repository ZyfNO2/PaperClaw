from __future__ import annotations

import os
from pathlib import Path
import re

import pytest
from playwright.sync_api import Browser, Page, sync_playwright


ASSET_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "paperclaw" / "desktop" / "static"
)


def load_app(page: Page) -> None:
    html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
    css = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
    javascript = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
    html = re.sub(
        r'<meta\s+http-equiv="Content-Security-Policy"[^>]*>',
        "",
        html,
        flags=re.IGNORECASE,
    )
    html = html.replace(
        '<link rel="stylesheet" href="styles.css">', f"<style>{css}</style>"
    )
    html = html.replace(
        '<script src="app.js"></script>', f"<script>{javascript}</script>"
    )
    page.set_content(html, wait_until="load")
    page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")


@pytest.fixture(scope="session")
def browser() -> Browser:
    if os.getenv("PAPERCLAW_RUN_PLAYWRIGHT") != "1":
        pytest.skip("Playwright desktop tests run only in the dedicated browser gate.")
    with sync_playwright() as playwright:
        executable = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable or None,
            args=["--allow-file-access-from-files"],
        )
        yield browser
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Page:
    page = browser.new_page(
        viewport={"width": 1440, "height": 900}, accept_downloads=True
    )
    yield page
    page.close()


def install_bridge(page: Page, *, auto_complete: bool = True) -> None:
    page.evaluate(
        f"""
        (() => {{
          const calls = {{ start: [], cancel: 0, select: 0, polls: 0, browser: [], themes: [] }};
          let state = {{
            run_id: null, status: 'idle', model_calls: 0, tool_calls: 0,
            last_sequence: 0, terminal: false, verification_status: null,
            verification_summary: null, final_result: null,
            error_code: null, error_message: null
          }};
          let queue = [];
          let theme = 'neo-brutalist';
          const autoComplete = {str(auto_complete).lower()};
          window.__bridgeCalls = calls;
          window.__mockState = () => state;
          window.pywebview = {{ api: {{
            async get_defaults() {{
              return {{
                ok: true,
                workspace: '/tmp/paperclaw-workspace',
                provider_source: 'env',
                provider: 'openai-compatible',
                base_url: 'https://provider.example/v1',
                model: 'env-model',
                configured: true,
                missing: [],
                theme
              }};
            }},
            async get_state() {{ return {{ ok: true, state }}; }},
            async start_run(payload) {{
              calls.start.push(JSON.parse(JSON.stringify(payload)));
              state = {{ ...state, status: 'starting', terminal: false, final_result: null }};
              queue.push(
                {{ kind: 'event', event: {{ sequence: 1, event_type: 'run.started', label: 'run.started' }} }},
                {{ kind: 'snapshot', snapshot: {{ ...state, run_id: 'run-e2e', status: 'running', last_sequence: 1 }} }},
                {{ kind: 'event', event: {{ sequence: 2, event_type: 'model.started', label: 'model.started · call=1' }} }},
                {{ kind: 'event', event: {{ sequence: 3, event_type: 'tool.completed', label: 'tool.completed · tool=file_write' }} }},
                {{ kind: 'event', event: {{ sequence: 4, event_type: 'verification.completed', label: 'verification.completed · verification=passed' }} }}
              );
              if (autoComplete) {{
                queue.push({{ kind: 'snapshot', snapshot: {{
                  run_id: 'run-e2e', status: 'completed', model_calls: 1, tool_calls: 1,
                  last_sequence: 4, terminal: true, verification_status: 'passed',
                  verification_summary: '3 checks passed', final_result: '任务完成：hello.py 已创建并验证。',
                  error_code: null, error_message: null
                }} }});
              }}
              return {{ ok: true, accepted: true, status: 'starting' }};
            }},
            async cancel_run() {{
              calls.cancel += 1;
              state = {{ ...state, run_id: 'run-e2e', status: 'cancelled', terminal: true }};
              queue.push({{ kind: 'snapshot', snapshot: state }});
              return {{ ok: true, accepted: true, status: 'stopping' }};
            }},
            async poll_events() {{
              calls.polls += 1;
              const items = queue.splice(0, queue.length);
              if (items.length) {{
                const snapshots = items.filter(item => item.kind === 'snapshot');
                if (snapshots.length) state = snapshots[snapshots.length - 1].snapshot;
              }}
              return {{ ok: true, items, dropped_count: 0 }};
            }},
            async select_workspace() {{
              calls.select += 1;
              return {{ ok: true, workspace: '/tmp/selected-workspace' }};
            }},
            async set_theme(theme) {{
              calls.themes.push(theme);
              return {{ ok: true, theme }};
            }},
            async open_in_browser(theme) {{
              calls.browser.push(theme);
              return {{ ok: true, opened: true, mode: 'browser', origin: 'http://127.0.0.1:4455' }};
            }}
          }} }};
        }})();
        """
    )
