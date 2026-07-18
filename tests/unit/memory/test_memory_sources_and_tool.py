from __future__ import annotations

import json
from pathlib import Path

from paperclaw.context.orchestration import ContextRequest
from paperclaw.memory import (
    FileMemoryStore,
    FrozenFoundationalContextSource,
    MemoryTool,
    ProjectInstructionLoader,
)
from paperclaw.tools.base import ToolContext


def test_project_instruction_loader_supports_bounded_workspace_imports(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    docs = workspace / "docs"
    docs.mkdir(parents=True)
    (workspace / "PAPERCLAW.md").write_text(
        "Use deterministic tests.\nSee @docs/architecture.md\n```\n@docs/ignored.md\n```\n",
        encoding="utf-8",
    )
    (docs / "architecture.md").write_text(
        "Keep the application boundary separate from tools.", encoding="utf-8"
    )
    (docs / "ignored.md").write_text("must not load", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("must not escape", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("@../outside.md", encoding="utf-8")

    snapshot = ProjectInstructionLoader(workspace).snapshot()

    assert "Use deterministic tests" in snapshot.content
    assert "application boundary" in snapshot.content
    assert "must not load" not in snapshot.content
    assert "must not escape" not in snapshot.content
    assert snapshot.source_files == ("PAPERCLAW.md", "docs/architecture.md", "AGENTS.md")


def test_frozen_context_source_keeps_session_start_profile(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = FileMemoryStore(tmp_path / "memory")
    store.add("user", "User prefers Chinese output.", category="communication")
    frozen = store.snapshot()
    project = ProjectInstructionLoader(workspace).snapshot()
    source = FrozenFoundationalContextSource(
        memory_snapshot=frozen,
        project_snapshot=project,
    )
    store.add("user", "User prefers Markdown tables.", category="preference")

    candidates = source.collect(
        ContextRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            step_id="model-1",
            raw_prompt="prompt",
            workspace=str(workspace),
        )
    )
    rendered = "\n".join(candidate.content for candidate in candidates)

    assert "Chinese output" in rendered
    assert "Markdown tables" not in rendered
    user = next(candidate for candidate in candidates if candidate.source == "long_memory_user")
    assert user.layer == "L1"
    assert user.pinned is True
    assert user.compressible is False


def test_memory_tool_reports_next_session_visibility_and_supports_delete(tmp_path: Path) -> None:
    store = FileMemoryStore(tmp_path / "memory")
    tool = MemoryTool(store)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = ToolContext(workspace)

    added = tool.execute(
        {
            "action": "add",
            "target": "user",
            "category": "preference",
            "content": "User prefers type hints.",
            "confidence": 0.9,
        },
        context,
    )
    assert added.ok is True
    payload = json.loads(added.output)
    assert payload["snapshot_visibility"] == "next_session"
    assert payload["usage"]["entries"] == 1

    removed = tool.execute(
        {"action": "remove", "target": "user", "old_text": "type hints"},
        context,
    )
    assert removed.ok is True
    assert store.list_entries("user") == ()


def test_memory_tool_rejects_unsupported_or_private_content(tmp_path: Path) -> None:
    store = FileMemoryStore(tmp_path / "memory")
    tool = MemoryTool(store)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = tool.execute(
        {
            "action": "add",
            "target": "memory",
            "content": "password=super-secret-value",
        },
        ToolContext(workspace),
    )

    assert result.ok is False
    assert result.error_code == "memory_write_failed"
    assert store.list_entries("memory") == ()
