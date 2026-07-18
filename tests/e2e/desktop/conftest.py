from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import Browser, Page, sync_playwright


ASSET_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "paperclaw" / "desktop" / "static"
)
_TEST_ORIGIN = ""
_TEST_READY_SCRIPT = "__paperclaw_test_ready.js"


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == f"/{_TEST_READY_SCRIPT}":
            body = b"window.__paperclawTestAssetsLoaded = true;"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split("?", 1)[0] in {"/", "/index.html"}:
            html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
            html = html.replace(
                "</body>",
                f'<script src="{_TEST_READY_SCRIPT}"></script></body>',
            )
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def _stage(name: str) -> None:
    print(f"PAPERCLAW_PLAYWRIGHT_STAGE={name}", flush=True)


def load_app(page: Page) -> None:
    """Load production Desktop modules over local HTTP with explicit readiness."""

    if not _TEST_ORIGIN:
        raise RuntimeError("desktop test HTTP origin is not initialized")
    _stage("goto-start")
    page.goto(f"{_TEST_ORIGIN}/index.html", wait_until="commit", timeout=5_000)
    _stage("goto-commit")
    page.wait_for_function(
        "() => window.__paperclawTestAssetsLoaded === true",
        timeout=5_000,
    )
    _stage("assets-ready")
    page.evaluate(
        """() => {
          document.dispatchEvent(new Event('DOMContentLoaded'));
          window.dispatchEvent(new Event('pywebviewready'));
        }"""
    )
    _stage("lifecycle-dispatched")
    page.wait_for_function(
        "() => document.querySelector('#workspace-path')?.textContent === '/tmp/paperclaw-workspace'",
        timeout=5_000,
    )
    _stage("workspace-ready")


@pytest.fixture(scope="session")
def desktop_origin() -> str:
    global _TEST_ORIGIN
    handler = partial(_QuietStaticHandler, directory=str(ASSET_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, name="paperclaw-playwright-http", daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    _TEST_ORIGIN = f"http://{host}:{port}"
    try:
        yield _TEST_ORIGIN
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _TEST_ORIGIN = ""


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
def page(browser: Browser, desktop_origin: str) -> Page:
    page = browser.new_page(
        viewport={"width": 1440, "height": 900}, accept_downloads=True
    )
    yield page
    page.close()


def install_bridge(page: Page, *, auto_complete: bool = True) -> None:
    """Install the pywebview bridge before the local HTTP page is created."""

    page.add_init_script(
        script=f"""
        (() => {{
          const calls = {{
            start: [], cancel: 0, select: 0, polls: 0, browser: [], themes: [],
            providerConnect: [], models: [], manual: [], clear: 0
          }};
          let state = {{
            run_id: null, status: 'idle', model_calls: 0, tool_calls: 0,
            last_sequence: 0, terminal: false, verification_status: null,
            verification_summary: null, final_result: null,
            error_code: null, error_message: null
          }};
          let queue = [];
          let theme = 'neo-brutalist';
          let providerState = {{
            ok: true,
            workspace: '/tmp/paperclaw-workspace',
            provider_source: 'env',
            provider: 'openai-compatible',
            base_url: 'https://provider.example/v1',
            model: 'env-model',
            available_models: ['env-model'],
            models: ['env-model'],
            configured: true,
            model_verified: true,
            model_source: 'environment',
            missing: []
          }};
          const autoComplete = {str(auto_complete).lower()};
          const clone = value => JSON.parse(JSON.stringify(value));
          const envProviderState = () => ({{
            ok: true,
            workspace: '/tmp/paperclaw-workspace',
            provider_source: 'env',
            provider: 'openai-compatible',
            base_url: 'https://provider.example/v1',
            model: 'env-model',
            available_models: ['env-model'],
            models: ['env-model'],
            configured: true,
            model_verified: true,
            model_source: 'environment',
            missing: [],
            manual_provider_cleared: true
          }});
          window.__bridgeCalls = calls;
          window.__mockState = () => state;
          window.pywebview = {{ api: {{
            async get_defaults() {{ return {{ ...clone(providerState), theme }}; }},
            async get_state() {{ return {{ ok: true, state }}; }},
            async start_run(payload) {{
              calls.start.push(clone(payload));
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
            async set_theme(nextTheme) {{
              theme = nextTheme;
              calls.themes.push(nextTheme);
              return {{ ok: true, theme }};
            }},
            async open_in_browser(nextTheme) {{
              calls.browser.push(nextTheme);
              return {{ ok: true, opened: true, mode: 'browser', origin: 'http://127.0.0.1:4455' }};
            }},
            async connect_provider(payload) {{
              calls.providerConnect.push(clone(payload));
              const model = payload.model || 'manual-model-a';
              providerState = {{
                ok: true,
                workspace: '/tmp/paperclaw-workspace',
                provider_source: 'manual',
                provider: payload.provider || 'openai-compatible',
                base_url: payload.base_url,
                model,
                selected_model: model,
                available_models: [model, 'manual-model-a', 'manual-model-b'],
                models: [model, 'manual-model-a', 'manual-model-b'],
                configured: true,
                model_verified: true,
                model_source: payload.model ? 'manual' : 'discovered',
                missing: []
              }};
              return clone(providerState);
            }},
            async select_provider_model(model, allowUnlisted = false) {{
              if (allowUnlisted) calls.manual.push(model);
              else calls.models.push(model);
              providerState = {{
                ...providerState,
                ok: true,
                provider_source: 'manual',
                model,
                selected_model: model,
                available_models: [model, 'manual-model-a', 'manual-model-b'],
                models: [model, 'manual-model-a', 'manual-model-b'],
                configured: true,
                model_source: allowUnlisted ? 'manual' : 'discovered',
                model_verified: !allowUnlisted
              }};
              return clone(providerState);
            }},
            async clear_provider_config() {{
              calls.clear += 1;
              providerState = envProviderState();
              return clone(providerState);
            }},
            async clear_manual_provider() {{
              calls.clear += 1;
              providerState = envProviderState();
              return clone(providerState);
            }}
          }} }};
        }})();
        """
    )
