from __future__ import annotations

import json
import os
from pathlib import Path
from time import monotonic, time
from uuid import uuid4

import pytest

from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.multiagent.tool import SubagentTaskTool
from paperclaw.tools.base import ToolContext


class MeteredModel:
    def __init__(self, inner, agent_id: str) -> None:
        self.inner = inner
        self.agent_id = agent_id
        self.provider = getattr(inner, "provider", None)
        self.model = getattr(inner, "model", None)
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.started_at: float | None = None
        self.completed_at: float | None = None

    def complete(self, prompt: str):
        if self.started_at is None:
            self.started_at = time()
        self.calls += 1
        turn = self.inner.complete(prompt)
        self.completed_at = time()
        metadata = getattr(turn, "metadata", {}) or {}
        self.input_tokens += _nonnegative(metadata.get("input_tokens"))
        self.output_tokens += _nonnegative(metadata.get("output_tokens"))
        return turn


def _nonnegative(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


@pytest.mark.real_llm
def test_live_mistral_parallel_isolated_subagents() -> None:
    api_key = os.getenv("PAPERCLAW_API_KEY", "").strip()
    if not api_key:
        pytest.fail("PAPERCLAW_API_KEY is required for live Mistral acceptance")

    workspace = Path.cwd().resolve()
    run_id = f"mistral-v018-{uuid4().hex[:12]}"
    models: dict[str, MeteredModel] = {}

    def factory(agent_id: str) -> MeteredModel:
        model = MeteredModel(OpenAICompatibleModel.from_env(), agent_id)
        models[agent_id] = model
        return model

    request = {
        "goal": (
            "Analyze two unrelated PaperClaw modules in parallel. Read files only; "
            "do not modify the repository. Return compact evidence-backed summaries."
        ),
        "max_agents": 2,
        "tasks": [
            {
                "task_id": "context-compaction",
                "title": "Context Compaction",
                "objective": (
                    "Inspect src/paperclaw/context runtime compaction and summarize "
                    "its boundaries, stop conditions, and one improvement."
                ),
                "acceptance_criteria": [
                    "Cite inspected module paths",
                    "Explain one bounded compaction behavior",
                ],
                "allowed_paths": ["src/paperclaw/context"],
                "writable_paths": [],
                "allowed_tools": ["file_read", "grep"],
                "dependencies": [],
                "max_steps": 8,
                "timeout_seconds": 180,
            },
            {
                "task_id": "mcp-permissions",
                "title": "MCP Permission Boundary",
                "objective": (
                    "Inspect PaperClaw MCP permission and policy code and summarize "
                    "the authorization boundary and one risk."
                ),
                "acceptance_criteria": [
                    "Cite inspected module paths",
                    "Explain one permission denial path",
                ],
                "allowed_paths": ["src/paperclaw/mcp", "src/paperclaw/policy"],
                "writable_paths": [],
                "allowed_tools": ["file_read", "grep"],
                "dependencies": [],
                "max_steps": 8,
                "timeout_seconds": 180,
            },
        ],
    }

    started = monotonic()
    result = SubagentTaskTool(factory).execute(
        request,
        ToolContext(
            workspace,
            output_limit=40_000,
            remaining_model_calls=20,
            remaining_tool_calls=20,
        ),
    )
    elapsed = monotonic() - started

    assert result.ok, result.output
    assert set(models) == {"worker-0", "worker-1"}
    windows = [
        (model.started_at, model.completed_at)
        for model in models.values()
        if model.started_at is not None and model.completed_at is not None
    ]
    assert len(windows) == 2
    overlap_seconds = max(
        0.0,
        min(windows[0][1], windows[1][1]) - max(windows[0][0], windows[1][0]),
    )
    assert overlap_seconds > 0, "Workers did not overlap at the Provider-call boundary"

    payload = json.loads(result.output)
    evidence = {
        "evidence_type": "live_provider",
        "provider": os.getenv("PAPERCLAW_PROVIDER", "mistral"),
        "model": os.getenv("PAPERCLAW_MODEL"),
        "parent_run_id": run_id,
        "subtask_ids": sorted(payload["tasks"]),
        "elapsed_seconds": round(elapsed, 3),
        "provider_overlap_seconds": round(overlap_seconds, 3),
        "parent_context_return_chars": len(result.output),
        "parent_context_added_tokens": sum(
            model.output_tokens for model in models.values()
        ),
        "workers": {
            agent_id: {
                "model_calls": model.calls,
                "input_tokens": model.input_tokens,
                "output_tokens": model.output_tokens,
                "started_at": model.started_at,
                "completed_at": model.completed_at,
            }
            for agent_id, model in sorted(models.items())
        },
        "tool_metadata": result.metadata,
        "task_statuses": {
            task_id: task["status"] for task_id, task in payload["tasks"].items()
        },
    }
    output = Path("tmp/v018-mistral-evidence.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
