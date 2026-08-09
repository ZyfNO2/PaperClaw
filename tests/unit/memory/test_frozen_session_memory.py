from __future__ import annotations

from pathlib import Path

from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.memory.repository import MemoryRepository
from paperclaw.memory.service import MemoryService


def test_session_snapshot_is_frozen_until_next_session(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "context.sqlite3")
    service = MemoryService(MemoryRepository(repo))
    try:
        first = service.add_memory(
            scope_type="PROJECT",
            scope_id="paperclaw",
            kind="constraint",
            content="QueryEngine remains a thin façade.",
            pinned=True,
        )
        session_one = SessionService.open(
            repo,
            conversation_id="conversation-1",
            memory_service=service,
            user_scope_id="user-1",
            project_scope_id="paperclaw",
        )
        snapshot_one = session_one.memory_snapshot
        assert snapshot_one is not None
        assert snapshot_one.memory_ids == (first.memory_id,)
        first_hash = snapshot_one.rendered_hash

        second = service.replace_memory(
            first.memory_id,
            content="QueryEngine remains a thin façade over the runtime.",
        )
        assert service.list_memory(scope_type="PROJECT", scope_id="paperclaw")[0].memory_id == second.memory_id
        assert session_one.memory_snapshot is snapshot_one
        assert session_one.memory_snapshot.rendered_hash == first_hash
        assert "thin façade over the runtime" not in snapshot_one.rendered_content

        session_two = SessionService.open(
            repo,
            conversation_id="conversation-2",
            memory_service=service,
            user_scope_id="user-1",
            project_scope_id="paperclaw",
        )
        assert session_two.memory_snapshot is not None
        assert session_two.memory_snapshot.memory_ids == (second.memory_id,)
        assert "thin façade over the runtime" in session_two.memory_snapshot.rendered_content
    finally:
        repo.close()
