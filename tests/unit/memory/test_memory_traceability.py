from __future__ import annotations

from pathlib import Path

from paperclaw.context.orchestration import ContextOrchestrator, ContextRequest
from paperclaw.context.repository import SQLiteRepository
from paperclaw.memory.context_source import StructuredMemoryContextSource
from paperclaw.memory.repository import MemoryRepository
from paperclaw.memory.service import MemoryService


def test_memory_lifecycle_events_and_context_traceability(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "context.sqlite3")
    events: list[tuple[str, dict]] = []
    service = MemoryService(
        MemoryRepository(repo),
        event_sink=lambda event_type, payload: events.append((event_type, payload)),
    )
    try:
        first = service.add_memory(
            scope_type="USER",
            scope_id="user-1",
            kind="user_preference",
            content="User prefers concise output.",
            source_refs=("event:run-1:3",),
            pinned=True,
            created_from_run_id="run-1",
            created_from_sequence=3,
        )
        snapshot = service.capture_snapshot(
            conversation_id="conversation-1",
            user_scope_id="user-1",
        )
        second = service.replace_memory(first.memory_id, content="User prefers concise Chinese output.")
        service.search_memory(
            "Chinese output",
            scopes=(("USER", "user-1"),),
        )
        service.remove_memory(second.memory_id)
        assert [name for name, _ in events] == [
            "memory.added",
            "memory.snapshot_created",
            "memory.replaced",
            "memory.retrieved",
            "memory.removed",
        ]
        assert events[0][1]["content_hash"] == first.content_hash
        assert events[1][1]["rendered_hash"] == snapshot.rendered_hash
        assert events[0][1]["source_refs"] == ["event:run-1:3"]
        source = StructuredMemoryContextSource(
            service,
            snapshot=snapshot,
            user_scope_id="user-1",
        )
        assembly = ContextOrchestrator(sources=(source,)).assemble(
            ContextRequest(
                run_id="run-1",
                conversation_id="conversation-1",
                step_id="model-1",
                raw_prompt="concise output",
                workspace=str(tmp_path),
            )
        )
        assert assembly.trace.memory_ids == (first.memory_id,)
        assert first.memory_id in assembly.trace.to_event_payload()["memory_ids"]
    finally:
        repo.close()
