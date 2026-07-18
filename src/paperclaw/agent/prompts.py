from __future__ import annotations

import json

from paperclaw.context.runtime_compaction import build_runtime_history_view
from paperclaw.tools.registry import ToolRegistry

from .events import emit_event


def build_prompt(shared: dict, registry: ToolRegistry) -> str:
    history = build_runtime_history_view(shared)
    sections = [
        "[Identity]\nYou are the minimal coding agent operating inside one workspace.",
        "[Rules]\nObserve before modifying. Select exactly one action. Never claim an unexecuted result. Do not install dependencies.",
        f"[Workspace]\n{shared['workspace']} (Windows PowerShell)",
        "[Tools]\n" + json.dumps(registry.descriptions(), ensure_ascii=False),
        "[CAS Contract]\n"
        "file_read returns content_hash in metadata. Before file_write on an existing file or any file_edit, "
        "you MUST first file_read the target file and pass the returned content_hash as expected_hash. "
        "For new files created via file_write, pass expected_hash as empty string \"\". "
        "Omitting or mismatching expected_hash returns cas_missing/cas_conflict and the file is not modified.",
        "[Task]\n" + shared["task"],
    ]
    if history.compacted:
        sections.extend(
            (
                "[History Summary]\n" + (history.summary_json or "{}"),
                "[Recent History]\n" + history.recent_history_json,
            )
        )
        if history.changed:
            emit_event(
                shared,
                "context.compaction.completed",
                step=shared.get("step_count", 0),
                method="deterministic_structured_extract_v1",
                original_tokens=history.original_tokens,
                rendered_tokens=history.rendered_tokens,
                covered_steps=list(history.covered_steps),
                recent_steps=list(history.recent_steps),
                fingerprint=history.fingerprint,
            )
    else:
        sections.append("[History]\n" + (history.full_history_json or "[]"))
    sections.append(
        '[Output Contract]\nReturn exactly one JSON object: {"action":"tool_name|done","arguments":{},"reason":"short audit note"}. For done, treat it as a completion proposal and use {"action":"done","arguments":{"result":"what is finished","verification":"what command/output verified it","remaining_issues":[]}}.'
    )
    return "\n\n".join(sections)
