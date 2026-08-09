from __future__ import annotations

import json
from pathlib import Path

from paperclaw.context.orchestration import ContextRequest
from paperclaw.context.repository import SQLiteRepository
from paperclaw.memory import MemoryRuntimeSettings, build_memory_runtime
from paperclaw.memory.repository import MemoryRepository
from paperclaw.memory.service import MemoryService
from paperclaw.tools.base import ToolContext


def test_runtime_registers_structured_memory_tool_and_l5_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = SQLiteRepository(tmp_path / "context.sqlite3")
    service = MemoryService(MemoryRepository(repo))
    service.add_memory(
        scope_type="PROJECT",
        scope_id="alpha",
        kind="decision",
        content="Use deterministic local retrieval.",
        pinned=True,
    )
    components = build_memory_runtime(
        workspace,
        settings=MemoryRuntimeSettings(memory_root=tmp_path / "legacy-memory"),
        repository=repo,
        conversation_id="conversation-1",
        user_scope_id="user-1",
        project_scope_id="alpha",
    )
    try:
        assert components.structured_memory_service is not None
        assert components.structured_memory_snapshot is not None
        assert "memory" in components.tool_registry.names
        descriptors = components.source_registry.snapshot().descriptors
        assert any(item.source_id == "structured_memory" for item in descriptors)
        candidates = components.source_registry.collect(
            ContextRequest(
                run_id="run-1",
                conversation_id="conversation-1",
                step_id="model-1",
                raw_prompt="deterministic retrieval",
                workspace=str(workspace),
            )
        )
        memory = next(item for item in candidates if item.source == "persistent_memory")
        assert memory.layer == "L5"
        assert memory.metadata["memory_mode"] == "pinned"

        tool = components.tool_registry.get("memory")
        tool.validate(
            {
                "action": "add",
                "scope_type": "PROJECT",
                "scope_id": "alpha",
                "kind": "lesson",
                "content": "The tool uses the structured service.",
            }
        )
        result = tool.execute(
            {
                "action": "add",
                "scope_type": "PROJECT",
                "scope_id": "alpha",
                "kind": "lesson",
                "content": "The tool uses the structured service.",
            },
            ToolContext(workspace),
        )
        assert result.ok is True
        assert json.loads(result.output)["memory"]["scope_type"] == "PROJECT"
    finally:
        components.close()
        repo.close()
