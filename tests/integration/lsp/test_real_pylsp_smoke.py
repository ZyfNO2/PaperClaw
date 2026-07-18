from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from paperclaw.lsp.client import LSPClient


pytestmark = pytest.mark.skipif(
    os.getenv("PAPERCLAW_RUN_REAL_LSP") != "1",
    reason="real pylsp smoke runs only in the dedicated v0.21 gate",
)


def test_real_pylsp_semantic_round_trip(tmp_path: Path) -> None:
    pylsp = shutil.which("pylsp")
    if not pylsp:
        pytest.fail("pylsp executable is required for real LSP acceptance")

    source = tmp_path / "demo.py"
    source.write_text(
        "def target(value: int) -> int:\n"
        "    return value + 1\n"
        "result = target(1)\n",
        encoding="utf-8",
    )

    client = LSPClient(
        [pylsp],
        workspace=tmp_path,
        language_id="python",
        request_timeout=10.0,
        initialize_timeout=20.0,
    )
    try:
        diagnostics = client.diagnostics(source, wait_seconds=3.0)
        assert isinstance(diagnostics, list)

        definition = client.definition(source, 2, 10)
        assert definition is not None

        references = client.references(
            source,
            0,
            4,
            include_declaration=True,
        )
        assert isinstance(references, list)
        assert references

        hover = client.hover(source, 0, 4)
        assert hover is not None

        symbols = client.document_symbols(source)
        assert isinstance(symbols, list)
        assert any(item.get("name") == "target" for item in symbols if isinstance(item, dict))
    finally:
        client.close()
