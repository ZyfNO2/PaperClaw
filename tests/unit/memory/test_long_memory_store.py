from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.memory import (
    FileMemoryStore,
    MemoryCapacityError,
    MemoryMatchError,
    MemoryPolicy,
    MemoryPrivacyError,
)


def test_user_profile_add_deduplicate_replace_and_remove(tmp_path: Path) -> None:
    store = FileMemoryStore(tmp_path / "memory")

    first = store.add(
        "user",
        "User prefers concise Chinese technical explanations.",
        category="communication",
        confidence=0.95,
    )
    duplicate = store.add(
        "user",
        "  User   prefers concise Chinese technical explanations.  ",
        category="communication",
        confidence=0.7,
    )
    assert duplicate.entry_id == first.entry_id

    replaced = store.replace(
        "user",
        "concise Chinese",
        "User prefers concise Chinese answers with structured technical detail.",
        confidence=0.98,
    )
    assert replaced.entry_id == first.entry_id
    assert replaced.confidence == 0.98
    assert "structured technical detail" in store.path_for("user").read_text(
        encoding="utf-8"
    )

    removed = store.remove("user", "structured technical")
    assert removed.entry_id == first.entry_id
    assert store.list_entries("user") == ()


def test_unique_substring_match_refuses_ambiguous_delete(tmp_path: Path) -> None:
    store = FileMemoryStore(tmp_path / "memory")
    store.add("memory", "Project uses Python 3.12.", category="project")
    store.add("memory", "Project uses SQLite for local durability.", category="project")

    with pytest.raises(MemoryMatchError, match="multiple entries"):
        store.remove("memory", "Project uses")


def test_capacity_overflow_is_explicit_and_does_not_modify_file(tmp_path: Path) -> None:
    store = FileMemoryStore(
        tmp_path / "memory",
        policy=MemoryPolicy(memory_char_limit=40, user_char_limit=40, max_entry_chars=80),
    )
    store.add("memory", "short durable fact", category="project")
    before = store.path_for("memory").read_text(encoding="utf-8")

    with pytest.raises(MemoryCapacityError):
        store.add("memory", "this second entry exceeds the bounded memory file", category="lesson")

    assert store.path_for("memory").read_text(encoding="utf-8") == before


def test_secret_shaped_content_is_rejected(tmp_path: Path) -> None:
    store = FileMemoryStore(tmp_path / "memory")

    with pytest.raises(MemoryPrivacyError):
        store.add("memory", "api_key=sk-this-should-never-be-persisted-123456")


def test_snapshot_is_frozen_and_new_writes_require_next_snapshot(tmp_path: Path) -> None:
    store = FileMemoryStore(tmp_path / "memory")
    store.add("user", "User prefers pytest.", category="preference")
    first = store.snapshot()

    store.add("memory", "Repository uses Ruff.", category="convention")
    second = store.snapshot()

    assert len(first.user_entries) == 1
    assert first.memory_entries == ()
    assert len(second.memory_entries) == 1
    assert first.fingerprint != second.fingerprint
