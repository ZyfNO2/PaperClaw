from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parents[3]
GENERATOR = ROOT / "scripts" / "generate_v0_14_canonical.py"


def test_canonical_generator_is_byte_reproducible(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for target in (first, second):
        subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                "--output-dir",
                str(target),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    first_json = first / "canonical_results.json"
    second_json = second / "canonical_results.json"
    first_md = first / "canonical_report.md"
    second_md = second / "canonical_report.md"
    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_md.read_bytes() == second_md.read_bytes()

    report = json.loads(first_json.read_text(encoding="utf-8"))
    assert report["dataset_digest"] == (
        "a0156e6d5c73ebde49b753b35ebc3337900897ab0f2c6f16b1e9cfcd94e8d774"
    )
    assert report["report_digest"] == (
        "68a82cc177bbe465515c11e727b9b351469f365de1a31d7e3972f4e0c5bbdbbc"
    )
    variants = {item["variant_id"]: item for item in report["variants"]}
    assert variants["baseline_no_retrieval"]["aggregate"]["recall_at_k"] == 0.0
    assert variants["bm25_mcp_verify"]["aggregate"]["recall_at_k"] == 1.0
