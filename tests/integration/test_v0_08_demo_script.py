from __future__ import annotations

import json
from pathlib import Path

from scripts.run_v0_08_context_demo import build_demo_artifact, main


def test_demo_artifact_is_deterministic_and_content_free() -> None:
    first = build_demo_artifact()
    second = build_demo_artifact()

    assert first["fingerprint"] == second["fingerprint"]
    assert all(first["checks"].values())
    serialized = json.dumps(first, ensure_ascii=False)
    assert "Produce one evidence-backed report" not in serialized
    assert "fabricate successful test results" not in serialized
    assert [section["name"] for section in first["sections"]] == [
        "RUNTIME PROTOCOL",
        "SELECTED CONTEXT",
        "UNTRUSTED DATA",
    ]


def test_demo_cli_writes_reproducible_json(tmp_path: Path) -> None:
    output = tmp_path / "v0_08_demo.json"

    assert main(["--output", str(output)]) == 0

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["version"] == "v0.08"
    assert all(artifact["checks"].values())
