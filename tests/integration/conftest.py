"""Integration-artifact normalization for reproducible committed traces.

The v0.04 demo intentionally writes a reviewable JSON artifact into the
repository. Runtime-generated identifiers, pytest temp paths, and timestamps
must not make that tracked file machine-specific or dirty the worktree after
every test run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest


_TRACE_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "v0_04"
    / "mvp_demo_trace.json"
)


def _normalize_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Replace volatile evidence fields with stable review placeholders."""
    stages = trace.get("stages", [])
    by_name = {
        stage.get("stage"): stage
        for stage in stages
        if isinstance(stage, dict)
    }

    setup = by_name.get("1_setup")
    if setup is not None:
        setup["db_path"] = "<pytest-temp>/demo.db"

    compaction = by_name.get("2_compaction")
    if compaction is not None:
        compaction["snapshot_id"] = "<snapshot_id>"
        compaction["source_item_ids"] = [
            "<compaction_summary_id>"
            if isinstance(item_id, str) and item_id.startswith("summary-")
            else item_id
            for item_id in compaction.get("source_item_ids", [])
        ]

    unsafe_resume = by_name.get("5_unsafe_resume")
    if unsafe_resume is not None:
        for operation in unsafe_resume.get("pending_operations", []):
            if isinstance(operation, dict) and "started_at" in operation:
                operation["started_at"] = "<runtime_timestamp>"

    return trace


@pytest.fixture(autouse=True)
def normalize_v0_04_demo_trace(request: pytest.FixtureRequest) -> Iterator[None]:
    """Normalize the tracked demo artifact after its integration test runs."""
    yield

    if request.node.name != "test_v0_04_mvp_demo":
        return
    if not _TRACE_PATH.exists():
        pytest.fail(f"expected v0.04 demo trace at {_TRACE_PATH}")

    with _TRACE_PATH.open("r", encoding="utf-8") as trace_file:
        trace = json.load(trace_file)

    normalized = _normalize_trace(trace)
    with _TRACE_PATH.open("w", encoding="utf-8", newline="\n") as trace_file:
        json.dump(normalized, trace_file, indent=2, ensure_ascii=False)
        trace_file.write("\n")
