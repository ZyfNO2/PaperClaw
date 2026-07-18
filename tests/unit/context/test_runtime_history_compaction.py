from __future__ import annotations

import json
from pathlib import Path

from paperclaw.agent.prompts import build_prompt
from paperclaw.agent.state import HistoryEntry
from paperclaw.context.runtime_compaction import (
    RuntimeCompactionPolicy,
    build_runtime_history_view,
)
from paperclaw.tools.base import ToolResult
from paperclaw.tools.registry import ToolRegistry


def _entry(step: int, *, ok: bool = True, output: str | None = None) -> HistoryEntry:
    return HistoryEntry(
        step=step,
        tool="file_read" if ok else "bash",
        arguments={"path": f"file-{step}.txt", "marker": f"arg-{step}"},
        reason=f"decision-{step}",
        result=ToolResult(
            ok,
            output or (f"output-{step}-" + "x" * 900),
            None if ok else "command_failed",
            {"evidence": f"ev-{step}"},
        ),
    )


def _shared(tmp_path: Path, history: list[HistoryEntry]) -> dict:
    return {
        "run_id": "run-context",
        "task": "Preserve the goal while compacting old observations.",
        "workspace": tmp_path,
        "history": history,
        "step_count": len(history),
        "event_sequence": 0,
        "trace_events": [],
        "remaining_issues": ["finish the final verification"],
        "event_handler": None,
    }


def test_compaction_keeps_full_audit_history_but_bounds_prompt_view(tmp_path: Path) -> None:
    history = [_entry(index, ok=index != 3) for index in range(1, 9)]
    shared = _shared(tmp_path, history)
    view = build_runtime_history_view(
        shared,
        policy=RuntimeCompactionPolicy(
            trigger_tokens=500,
            target_tokens=900,
            recent_entries=3,
        ),
    )

    assert view.compacted is True
    assert view.covered_steps
    assert view.recent_steps
    assert len(shared["history"]) == 8
    assert "failed_attempts" in (view.summary_json or "")
    assert "command_failed" in (view.summary_json or "")
    assert "finish the final verification" in (view.summary_json or "")
    assert view.rendered_tokens < view.original_tokens
    assert shared["history_compaction"]["method"] == "deterministic_structured_extract_v1"


def test_prompt_switches_to_summary_and_emits_auditable_event(tmp_path: Path) -> None:
    old_payload = "OLD-EVIDENCE-" + "q" * 2_000 + "-SHOULD-NOT-BE-IN-PROMPT"
    history = [_entry(1, output=old_payload)] + [_entry(index) for index in range(2, 10)]
    shared = _shared(tmp_path, history)

    prompt = build_prompt(shared, ToolRegistry())

    assert "[History Summary]" in prompt
    assert "[Recent History]" in prompt
    assert "SHOULD-NOT-BE-IN-PROMPT" not in prompt
    assert len(shared["history"]) == len(history)
    events = [
        event
        for event in shared["trace_events"]
        if event["event_type"] == "context.compaction.completed"
    ]
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["covered_steps"]
    assert payload["recent_steps"]
    assert payload["rendered_tokens"] < payload["original_tokens"]


def test_oversized_recent_output_is_bounded_with_hash_reference(tmp_path: Path) -> None:
    history = [_entry(index) for index in range(1, 8)]
    history[-1] = _entry(7, output="RECENT-START-" + "中" * 20_000 + "-RECENT-END")
    shared = _shared(tmp_path, history)
    view = build_runtime_history_view(
        shared,
        policy=RuntimeCompactionPolicy(
            trigger_tokens=500,
            target_tokens=1_500,
            recent_entries=3,
            max_recent_output_chars=500,
        ),
    )

    records = json.loads(view.recent_history_json)
    latest = records[-1]["result"]
    assert latest["output_truncated"] is True
    assert latest["output_sha256"]
    assert "RECENT-END" not in latest["output"]
    assert len(shared["history"][-1].result.output) > 20_000


def test_small_history_preserves_legacy_prompt_shape(tmp_path: Path) -> None:
    shared = _shared(tmp_path, [_entry(1, output="small")])

    prompt = build_prompt(shared, ToolRegistry())

    assert "[History]\n[" in prompt
    assert "[History Summary]" not in prompt
    assert shared["history_compaction"]["compacted"] is False
