from __future__ import annotations

import json
from pathlib import Path

from scripts.run_v0_09_1_rag_demo import run_demo


def test_offline_rag_demo_is_grounded_and_injection_contained(tmp_path: Path) -> None:
    output = tmp_path / "rag-demo.json"
    first = run_demo(output)
    second = run_demo()

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == first
    assert first == second
    assert first["decision"]["answerable"] is True
    assert first["anchors"]
    assert first["assembly"]["injection_in_runtime_protocol"] is False
    assert first["assembly"]["injection_contained_in_untrusted_data"] is True
    assert first["grounding_metrics"]["citation_correctness"] == 1.0
    assert first["grounding_metrics"]["unsupported_claim_rate"] == 0.0
    assert first["grounding_metrics"]["abstention_accuracy"] == 1.0
