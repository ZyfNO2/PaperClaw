from __future__ import annotations

from pathlib import Path

from paperclaw.context.orchestration import ContextRequest
from paperclaw.context.repository import SQLiteRepository
from paperclaw.memory.context_source import StructuredMemoryContextSource
from paperclaw.memory.repository import MemoryRepository
from paperclaw.memory.service import MemoryService


def test_l5_source_keeps_pinned_snapshot_and_recalls_new_active_memory(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "context.sqlite3")
    service = MemoryService(MemoryRepository(repo))
    try:
        old = service.add_memory(
            scope_type="PROJECT",
            scope_id="alpha",
            kind="constraint",
            content="The old pinned constraint.",
            pinned=True,
        )
        snapshot = service.capture_snapshot(
            conversation_id="conversation-1",
            user_scope_id="user-1",
            project_scope_id="alpha",
        )
        new = service.replace_memory(
            old.memory_id,
            content="The new durable constraint.",
        )
        source = StructuredMemoryContextSource(
            service,
            snapshot=snapshot,
            user_scope_id="user-1",
            project_scope_id="alpha",
        )
        candidates = source.collect(
            ContextRequest(
                run_id="run-1",
                conversation_id="conversation-1",
                step_id="model-1",
                raw_prompt="new durable constraint",
                workspace=str(tmp_path),
            )
        )
        by_mode = {candidate.metadata["memory_mode"]: candidate for candidate in candidates}
        assert by_mode["pinned"].metadata["memory_id"] == old.memory_id
        assert by_mode["pinned"].layer == "L5"
        assert by_mode["retrieved"].metadata["memory_id"] == new.memory_id
        assert by_mode["retrieved"].metadata["memory_mode"] == "retrieved"
    finally:
        repo.close()
