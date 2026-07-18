from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from paperclaw.lsp.manager import LSPConfigurationError, LSPManager, LanguageServerConfig
from paperclaw.lsp.tools import (
    LSPDefinitionTool,
    LSPDiagnosticsTool,
    LSPHoverTool,
    LSPReferencesTool,
    LSPSymbolsTool,
)
from paperclaw.tools.base import ToolContext


FAKE_SERVER = Path(__file__).resolve().parents[2] / "fixtures" / "fake_lsp_server.py"


def _manager(tmp_path: Path) -> LSPManager:
    return LSPManager(
        tmp_path,
        [
            LanguageServerConfig(
                name="fake-python",
                command=(sys.executable, str(FAKE_SERVER)),
                language_id="python",
                extensions=(".py",),
                request_timeout=1.0,
                initialize_timeout=2.0,
            )
        ],
    )


def _payload(result) -> dict:
    assert result.ok is True
    return json.loads(result.output)


def test_manager_enforces_workspace_and_configured_extensions(tmp_path: Path) -> None:
    source = tmp_path / "demo.py"
    source.write_text("value = 1\n", encoding="utf-8")
    manager = _manager(tmp_path)
    outside = tmp_path.parent / "outside-paperclaw-test.py"
    outside.write_text("value = 2\n", encoding="utf-8")
    try:
        resolved, _ = manager.resolve("demo.py")
        assert resolved == source.resolve()

        with pytest.raises(PermissionError, match="escapes workspace"):
            manager.resolve(outside)

        text_file = tmp_path / "notes.txt"
        text_file.write_text("notes", encoding="utf-8")
        with pytest.raises(LSPConfigurationError, match="no language server"):
            manager.resolve(text_file)
    finally:
        manager.close()
        outside.unlink(missing_ok=True)


def test_manager_restarts_closed_language_server(tmp_path: Path) -> None:
    source = tmp_path / "demo.py"
    source.write_text("value = 1\n", encoding="utf-8")
    manager = _manager(tmp_path)
    try:
        _, first = manager.resolve(source)
        first.close()
        assert first.returncode is not None

        _, second = manager.resolve(source)
        assert second is not first
        assert second.returncode is None
    finally:
        manager.close()


def test_all_lsp_tools_return_bounded_structured_results(tmp_path: Path) -> None:
    source = tmp_path / "demo.py"
    source.write_text("def demo():\n    return 1\n", encoding="utf-8")
    manager = _manager(tmp_path)
    context = ToolContext(tmp_path, output_limit=20_000)
    try:
        diagnostics = _payload(
            LSPDiagnosticsTool(manager).execute(
                {"path": "demo.py", "wait_seconds": 1.0}, context
            )
        )
        assert diagnostics["operation"] == "lsp_diagnostics"
        assert diagnostics["result"][0]["code"] == "FAKE001"

        definition = _payload(
            LSPDefinitionTool(manager).execute(
                {"path": "demo.py", "line": 0, "character": 4}, context
            )
        )
        assert definition["operation"] == "lsp_definition"

        references = _payload(
            LSPReferencesTool(manager).execute(
                {
                    "path": "demo.py",
                    "line": 0,
                    "character": 4,
                    "include_declaration": True,
                },
                context,
            )
        )
        assert len(references["result"]) == 2

        hover = _payload(
            LSPHoverTool(manager).execute(
                {"path": "demo.py", "line": 0, "character": 4}, context
            )
        )
        assert "demo" in hover["result"]["contents"]["value"]

        symbols = _payload(
            LSPSymbolsTool(manager).execute({"path": "demo.py"}, context)
        )
        assert symbols["result"][0]["name"] == "demo"

        workspace_symbols = _payload(
            LSPSymbolsTool(manager).execute({"query": "demo"}, context)
        )
        assert workspace_symbols["result"][0]["server"] == "fake-python"
    finally:
        manager.close()
