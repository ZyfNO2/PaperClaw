from __future__ import annotations

from pathlib import Path

from paperclaw.memory import FileMemoryStore, MemoryRuntimeSettings, build_memory_runtime


def test_runtime_composition_registers_memory_tool_and_freezes_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "PAPERCLAW.md").write_text("Always run focused tests.", encoding="utf-8")
    store = FileMemoryStore(tmp_path / "memories")
    store.add("user", "User prefers concise output.", category="communication")
    settings = MemoryRuntimeSettings(
        memory_root=tmp_path / "memories",
        max_input_tokens=8_000,
        output_reserve_tokens=1_000,
    )

    components = build_memory_runtime(workspace, settings=settings, store=store)

    assert "memory" in components.tool_registry.names
    snapshot = components.source_registry.snapshot()
    assert snapshot.descriptors[0].source_id == "foundational_context"
    assert components.snapshot.user_entries[0].content == "User prefers concise output."
    assert components.context_policy.available_input_tokens == 7_000


def test_runtime_composition_can_disable_memory_but_keep_project_context(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("Use repository conventions.", encoding="utf-8")
    store = FileMemoryStore(tmp_path / "memories")
    store.add("user", "User profile should be disabled.", category="preference")
    settings = MemoryRuntimeSettings(
        memory_enabled=False,
        memory_tool_enabled=False,
        memory_root=tmp_path / "memories",
    )

    components = build_memory_runtime(workspace, settings=settings, store=store)

    assert "memory" not in components.tool_registry.names
    assert components.snapshot.user_entries == ()
    assert components.source_registry.snapshot().descriptors
