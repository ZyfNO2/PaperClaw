from __future__ import annotations

import inspect
import json
import re
from importlib.resources import files
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from paperclaw.desktop import app
import paperclaw.desktop.bootstrap  # noqa: F401  # installs supported extensions


def _positional_arity(method: object) -> tuple[int, int]:
    parameters = list(inspect.signature(method).parameters.values())[1:]
    positional = [
        item
        for item in parameters
        if item.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    required = sum(item.default is inspect.Parameter.empty for item in positional)
    return required, len(positional)


def test_browser_allowlist_matches_desktop_api_signatures() -> None:
    for name, expected in app._BROWSER_API_ARITY.items():
        method = getattr(app.DesktopAPI, name, None)
        assert callable(method), f"registered browser method {name!r} is missing"
        assert _positional_arity(method) == expected, name


def test_shared_frontend_client_covers_exact_browser_allowlist() -> None:
    source = files("paperclaw.desktop").joinpath("static", "transport.js").read_text(
        encoding="utf-8"
    )
    declared = set(re.findall(r"^\s{4}([a-z][a-z0-9_]+):", source, re.MULTILINE))

    assert set(app._BROWSER_API_ARITY) <= declared
    assert "Proxy(" not in source
    assert "window.PaperClawBackend" in source


def test_page_modules_do_not_implement_parallel_transports() -> None:
    static = files("paperclaw.desktop").joinpath("static")
    for name in ("app.js", "papers.js", "product.js", "provider-config.js"):
        source = static.joinpath(name).read_text(encoding="utf-8")
        assert "X-PaperClaw-Token" not in source
        assert "window.fetch(`/api/" not in source
        assert "PaperClawBackend" in source


def test_every_allowlisted_method_has_same_direct_and_http_dispatch_semantics() -> None:
    api = app.DesktopAPI(object())
    host = app._BrowserHost(api)
    for name in app._BROWSER_API_ARITY:
        setattr(
            api,
            name,
            lambda *args, method=name: {"ok": True, "method": method, "args": list(args)},
        )
    host.start()
    try:
        for name, (minimum, maximum) in app._BROWSER_API_ARITY.items():
            args = [f"arg-{index}" for index in range(minimum)]
            direct = getattr(api, name)(*args)
            request = Request(
                f"{host.origin}/api/{name}",
                data=json.dumps({"args": args}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-PaperClaw-Token": host._token,
                },
                method="POST",
            )
            with urlopen(request, timeout=3) as response:
                browser = json.loads(response.read())
            assert browser == direct

            invalid_args = [None] * (maximum + 1)
            invalid = Request(
                f"{host.origin}/api/{name}",
                data=json.dumps({"args": invalid_args}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-PaperClaw-Token": host._token,
                },
                method="POST",
            )
            with pytest.raises(HTTPError) as rejected:
                urlopen(invalid, timeout=3)
            assert rejected.value.code == 400
            assert json.loads(rejected.value.read())["error_code"] == "validation_error"
    finally:
        host.stop()
