from __future__ import annotations

import json

from paperclaw.tools.registry import ToolRegistry


def build_prompt(shared: dict, registry: ToolRegistry) -> str:
    history = [entry.to_dict() for entry in shared["history"]]
    return "\n\n".join(
        [
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
            "[History]\n" + json.dumps(history, ensure_ascii=False),
            '[Output Contract]\nReturn exactly one JSON object: {"action":"tool_name|done","arguments":{},"reason":"short audit note"}. For done, treat it as a completion proposal and use {"action":"done","arguments":{"result":"what is finished","verification":"what command/output verified it","remaining_issues":[]}}.',
        ]
    )
