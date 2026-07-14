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
            "[Task]\n" + shared["task"],
            "[History]\n" + json.dumps(history, ensure_ascii=False),
            '[Output Contract]\nReturn exactly one JSON object: {"action":"tool_name|done","arguments":{},"reason":"short audit note"}. For done, use {"action":"done","arguments":{"result":"what is finished","verification":"what command/output verified it","remaining_issues":[]}}.',
        ]
    )
