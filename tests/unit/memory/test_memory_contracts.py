from __future__ import annotations

import hashlib

import pytest

from paperclaw.memory.contracts import (
    MemoryContractError,
    MemoryItem,
    MemoryKind,
    MemoryScope,
    MemorySnapshot,
)


def test_memory_item_normalizes_and_round_trips() -> None:
    item = MemoryItem(
        scope_type=MemoryScope.PROJECT,
        scope_id="paperclaw",
        kind=MemoryKind.CONSTRAINT,
        content="  QueryEngine remains a thin façade. ",
        source_refs=["event:run-1:4", "event:run-1:4"],  # type: ignore[arg-type]
        importance=90,
        pinned=True,
    )

    assert item.scope_type == "PROJECT"
    assert item.kind == "constraint"
    assert item.content == "QueryEngine remains a thin façade."
    assert item.source_refs == ("event:run-1:4",)
    assert item.content_hash == hashlib.sha256(item.content.encode()).hexdigest()
    assert MemoryItem.from_dict(item.to_dict()) == item


@pytest.mark.parametrize("scope", ["TEAM", "", "project-a"])
def test_unsupported_scope_fails_closed(scope: str) -> None:
    with pytest.raises(MemoryContractError, match="scope"):
        MemoryItem(scope, "id", "decision", "content")


def test_unknown_kind_and_empty_content_are_rejected() -> None:
    with pytest.raises(MemoryContractError, match="kind"):
        MemoryItem("USER", "user-1", "profile", "content")
    with pytest.raises(MemoryContractError, match="content"):
        MemoryItem("USER", "user-1", "user_preference", "  ")


def test_self_supersession_and_hash_tampering_are_rejected() -> None:
    with pytest.raises(MemoryContractError, match="supersedes"):
        MemoryItem(
            "USER", "user-1", "user_preference", "content", memory_id="m1", supersedes_memory_id="m1"
        )
    with pytest.raises(MemoryContractError, match="content_hash"):
        MemoryItem(
            "USER", "user-1", "user_preference", "content", content_hash="bad"
        )


def test_snapshot_hash_is_deterministic_and_validated() -> None:
    rendered = "[mem-1] QueryEngine remains thin."
    snapshot = MemorySnapshot(
        conversation_id="conversation-1",
        memory_ids=("mem-1",),
        rendered_content=rendered,
        rendered_hash=hashlib.sha256(rendered.encode()).hexdigest(),
        estimated_tokens=8,
    )
    assert snapshot.to_dict()["memory_ids"] == ["mem-1"]
    with pytest.raises(MemoryContractError, match="rendered_hash"):
        MemorySnapshot(
            conversation_id="conversation-1",
            memory_ids=("mem-1",),
            rendered_content=rendered,
            rendered_hash="bad",
            estimated_tokens=8,
        )
