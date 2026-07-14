"""Deterministic end-to-end demo for the v0.05 QueryEngine MVP."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.tools import FileWriteTool, ToolRegistry
from paperclaw.tools.base import (
    ToolContext,
    ToolResult,
    ToolValidationError,
    require_string,
)
from tests.helpers import FakeModel, action, done


class RunPythonTool:
    name = "run_python"
    description = "Run one Python file inside the test workspace."

    def validate(self, arguments: dict) -> None:
        path = require_string(arguments, "path")
        if not path.endswith(".py"):
            raise ToolValidationError("path must point to a Python file")

    def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        target = (context.workspace / arguments["path"]).resolve()
        if not target.is_relative_to(context.workspace):
            return ToolResult(False, "path escapes workspace", "path_escape")
        completed = subprocess.run(
            [sys.executable, str(target)],
            cwd=context.workspace,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = (completed.stdout + completed.stderr).strip()
        return ToolResult(
            completed.returncode == 0,
            output,
            None if completed.returncode == 0 else "command_failed",
            {"exit_code": completed.returncode},
        )


def test_v0_05_mvp_demo(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    model = FakeModel(
        [
            action(
                "file_write",
                {"path": "hello.py", "content": "print('hello')\n"},
                reason="create file",
            ),
            action("run_python", {"path": "hello.py"}, reason="run file"),
            done(result="hello.py executed", verification="process exited 0"),
        ]
    )
    registry = ToolRegistry([FileWriteTool(), RunPythonTool()])
    engine = QueryEngine(
        AgentRuntimeExecutor(model, tmp_path, registry=registry),
        conversation_id="conv-v0-05-demo",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    )

    result = engine.submit(
        "create hello.py, run it, and verify",
        limits=RunLimits(max_steps=6, max_model_calls=5, max_tool_calls=4),
    )

    normalized_events = []
    for event_type, payload in events:
        normalized = dict(payload)
        normalized["run_id"] = "<run_id>"
        normalized_events.append(
            {"event_type": event_type, "payload": normalized}
        )
    normalized_result = asdict(result)
    normalized_result["run_id"] = "<run_id>"
    trace = {
        "schema_version": 1,
        "scenario": "create-run-verify",
        "result": normalized_result,
        "events": normalized_events,
        "assertions": {
            "created_file": (tmp_path / "hello.py").exists(),
            "event_sequence_monotonic": [
                payload["sequence"] for _, payload in events
            ]
            == list(range(1, len(events) + 1)),
            "terminal_event_count": sum(
                event_type in {"run.completed", "run.failed", "run.stopped"}
                for event_type, _ in events
            ),
            "tool_validation_path_preserved": True,
        },
    }

    artifact_path = (
        Path(__file__).resolve().parents[2]
        / "artifacts"
        / "v0_05"
        / "mvp_demo_trace.json"
    )
    expected = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result.status == "completed"
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert trace == expected
