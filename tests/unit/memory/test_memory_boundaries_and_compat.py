from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.memory import MemoryRuntimeSettings, build_memory_runtime
from paperclaw.memory.contracts import MemoryBoundaryError
from paperclaw.memory.repository import MemoryRepository
from paperclaw.memory.service import MemoryService


def test_memory_remains_separate_from_transcript_and_source_bodies(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "context.sqlite3")
    service = MemoryService(MemoryRepository(repo))
    try:
        session = SessionService.open(repo, conversation_id="conversation-1")
        session.append_message("user", "A complete transcript that is not Memory.")
        item = service.add_memory(
            scope_type="PROJECT",
            scope_id="alpha",
            kind="decision",
            content="Use the evidence reference when verifying this decision.",
            source_refs=("evidence:verified:42", "artifact:report:7"),
        )
        messages = repo.list_messages("conversation-1")
        assert len(messages) == 1
        assert "complete transcript" in messages[0]["content"]
        assert repo.get_memory_item(item.memory_id).content == (
            "Use the evidence reference when verifying this decision."
        )
        with pytest.raises(MemoryBoundaryError):
            service.add_memory(
                scope_type="PROJECT",
                scope_id="alpha",
                kind="lesson",
                content="<transcript>" + "source body " * 100,
            )
    finally:
        repo.close()


def test_disabled_structured_memory_preserves_the_existing_runtime_shape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = SQLiteRepository(tmp_path / "context.sqlite3")
    components = build_memory_runtime(
        workspace,
        repository=repo,
        settings=MemoryRuntimeSettings(
            memory_enabled=False,
            user_profile_enabled=False,
            memory_tool_enabled=False,
            memory_root=tmp_path / "legacy-memory",
        ),
    )
    try:
        assert components.structured_memory_service is None
        assert components.structured_memory_snapshot is None
        assert "memory" not in components.tool_registry.names
        assert [item.source_id for item in components.source_registry.snapshot().descriptors] == [
            "foundational_context"
        ]
    finally:
        components.close()
        repo.close()
