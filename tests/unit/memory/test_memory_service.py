from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.context.repository import SQLiteRepository
from paperclaw.memory.contracts import MemoryBoundaryError, MemoryTrustError
from paperclaw.memory.repository import MemoryRepository
from paperclaw.memory.service import MemoryService


def _service(tmp_path: Path) -> tuple[SQLiteRepository, MemoryService]:
    repo = SQLiteRepository(tmp_path / "context.sqlite3")
    return repo, MemoryService(MemoryRepository(repo))


def test_add_list_replace_and_remove_preserve_immutable_history(tmp_path: Path) -> None:
    repo, service = _service(tmp_path)
    try:
        first = service.add_memory(
            scope_type="PROJECT",
            scope_id="alpha",
            kind="project_fact",
            content="Project uses SQLite.",
            pinned=True,
        )
        second = service.replace_memory(
            first.memory_id,
            content="Project uses SQLite with WAL.",
            created_from_run_id="run-1",
            created_from_sequence=4,
        )
        tombstone = service.remove_memory(second.memory_id)

        assert service.list_memory(scope_type="PROJECT", scope_id="alpha") == []
        history = service.list_memory(
            scope_type="PROJECT", scope_id="alpha", include_history=True
        )
        assert [item.memory_id for item in history] == [
            first.memory_id,
            second.memory_id,
            tombstone.memory_id,
        ]
        assert repo.get_memory_item(first.memory_id).content == "Project uses SQLite."
        assert tombstone.tombstone is True
    finally:
        repo.close()


def test_scope_isolation_and_lexical_recall_are_fail_closed(tmp_path: Path) -> None:
    repo, service = _service(tmp_path)
    try:
        user = service.add_memory(
            scope_type="USER", scope_id="u1", kind="user_preference", content="Prefers concise answers."
        )
        service.add_memory(
            scope_type="PROJECT", scope_id="alpha", kind="project_fact", content="Alpha uses SQLite."
        )
        service.add_memory(
            scope_type="PROJECT", scope_id="beta", kind="project_fact", content="Beta uses Postgres."
        )
        assert [item.memory_id for item in service.list_memory(scope_type="PROJECT", scope_id="beta")] != [user.memory_id]
        recalled = service.search_memory("SQLite", scopes=(("PROJECT", "alpha"),))
        assert [item.content for item in recalled] == ["Alpha uses SQLite."]
        with pytest.raises(ValueError, match="USER or PROJECT"):
            service.list_memory(scope_type="TEAM", scope_id="all")
    finally:
        repo.close()


def test_external_untrusted_and_source_bodies_are_not_promoted(tmp_path: Path) -> None:
    repo, service = _service(tmp_path)
    try:
        with pytest.raises(MemoryTrustError):
            service.add_memory(
                scope_type="PROJECT",
                scope_id="alpha",
                kind="lesson",
                content="A web page claims X.",
                trust_level="external_untrusted",
                source_refs=("external:web:1",),
            )
        confirmed = service.add_memory(
            scope_type="PROJECT",
            scope_id="alpha",
            kind="lesson",
            content="User confirmed the durable conclusion.",
            trust_level="external_untrusted",
            source_refs=("external:web:1",),
            explicit_user_confirmation=True,
        )
        assert confirmed.trust_level == "user"
        with pytest.raises(MemoryBoundaryError):
            service.add_memory(
                scope_type="PROJECT",
                scope_id="alpha",
                kind="lesson",
                content="x" * 4_001,
            )
    finally:
        repo.close()
