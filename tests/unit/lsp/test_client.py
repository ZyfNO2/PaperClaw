from __future__ import annotations

from pathlib import Path
import sys

import pytest

from paperclaw.lsp.client import JsonRpcTransport, LSPClient, LSPTimeoutError


FAKE_SERVER = Path(__file__).resolve().parents[2] / "fixtures" / "fake_lsp_server.py"


def _client(tmp_path: Path) -> LSPClient:
    return LSPClient(
        [sys.executable, str(FAKE_SERVER)],
        workspace=tmp_path,
        language_id="python",
        request_timeout=1.0,
        initialize_timeout=2.0,
    )


def test_fake_server_supports_read_only_semantic_operations(tmp_path: Path) -> None:
    source = tmp_path / "demo.py"
    source.write_text("def demo():\n    return 1\n", encoding="utf-8")
    client = _client(tmp_path)
    try:
        diagnostics = client.diagnostics(source)
        assert diagnostics[0]["code"] == "FAKE001"

        definition = client.definition(source, 0, 4)
        assert definition["uri"] == source.as_uri()

        references = client.references(source, 0, 4, include_declaration=True)
        assert len(references) == 2

        hover = client.hover(source, 0, 4)
        assert "demo" in hover["contents"]["value"]

        symbols = client.document_symbols(source)
        assert symbols[0]["name"] == "demo"

        workspace_symbols = client.workspace_symbols("demo")
        assert workspace_symbols[0]["name"] == "demo"
    finally:
        client.close()


def test_diagnostics_wait_for_notification_after_document_change(tmp_path: Path) -> None:
    source = tmp_path / "demo.py"
    source.write_text("value = 1\n", encoding="utf-8")
    client = _client(tmp_path)
    try:
        first = client.diagnostics(source)
        assert first[0]["code"] == "FAKE001"

        source.write_text("value = 2\n", encoding="utf-8")
        second = client.diagnostics(source)

        assert second[0]["code"] == "FAKE002"
        assert second[0]["message"] == "updated deterministic diagnostic"
    finally:
        client.close()


def test_json_rpc_request_timeout_is_typed_and_transport_can_close(tmp_path: Path) -> None:
    transport = JsonRpcTransport(
        [sys.executable, str(FAKE_SERVER)],
        cwd=tmp_path,
    )
    try:
        initialized = transport.request(
            "initialize",
            {"rootUri": tmp_path.as_uri()},
            timeout=1.0,
        )
        assert initialized["capabilities"]["definitionProvider"] is True

        with pytest.raises(LSPTimeoutError, match="paperclaw/sleep"):
            transport.request(
                "paperclaw/sleep",
                {"seconds": 0.2},
                timeout=0.01,
            )
    finally:
        transport.close()
