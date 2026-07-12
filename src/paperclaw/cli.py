from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from paperclaw.agent.flow import AgentRuntime
from paperclaw.models.adapters import OpenAICompatibleModel


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip())


def console_print(text: str = "") -> None:
    stream = sys.stdout
    encoding = stream.encoding or "utf-8"
    safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    stream.write(safe + "\n")
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PaperClaw v0.01 coding agent")
    parser.add_argument("task")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--verbose-events", action="store_true")
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env")

    def print_event(event: str, payload: dict) -> None:
        if not args.verbose_events:
            return
        if event == "reasoning":
            console_print(f"[step {payload['step']}] thinking")
            console_print(payload["reasoning"].strip())
        elif event == "tool_call":
            console_print(f"[step {payload['step']}] tool -> {payload['tool']}")
            console_print(f"reason: {payload['reason']}")
            console_print(json.dumps(payload["arguments"], ensure_ascii=False, indent=2))
        elif event == "tool_result":
            status = "ok" if payload["ok"] else "failed"
            console_print(f"[step {payload['step']}] result <- {payload['tool']} ({status})")
            if payload["error_code"]:
                console_print(f"error: {payload['error_code']}")
            if payload["output"]:
                console_print(payload["output"])
        elif event == "invalid_model_output":
            console_print(f"[step {payload['step']}] invalid model output")
            console_print(payload["error"])
        elif event == "done":
            console_print(f"[step {payload['step']}] done")
            console_print(f"result: {payload['result']}")
            console_print(f"verification: {payload['verification_status']}")
        elif event == "stop":
            console_print(f"stopped: {payload['reason']}")

    state = AgentRuntime(OpenAICompatibleModel.from_env()).run(args.task, args.workspace, args.max_steps, event_handler=print_event)
    safe_state = {key: value for key, value in state.items() if key not in {"workspace", "current_tool_call", "event_handler"}}
    safe_state["history"] = [entry.to_dict() for entry in state["history"]]
    console_print(json.dumps(safe_state, ensure_ascii=False, indent=2))
    return 0 if state["stop_reason"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
