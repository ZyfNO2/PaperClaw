"""Tests for scoped tool wrappers: idempotency, CAS, and FileSnapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.multiagent.contracts import AgentTask
from paperclaw.multiagent.lease import LeaseManager
from paperclaw.multiagent.permissions import PermissionGuardLite
from paperclaw.multiagent.scoped_tools import FileSnapshot, ScopedFileWriteTool, WorkerRuntimeCounters
from paperclaw.tools.base import ToolContext


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path


@pytest.fixture
def write_tool(tmp_workspace: Path) -> ScopedFileWriteTool:
    task = AgentTask(
        task_id="t1",
        title="write",
        objective="write a file",
        acceptance_criteria=["file exists"],
        allowed_paths=["."],
        writable_paths=["src"],
        allowed_tools=["file_write"],
    )
    return ScopedFileWriteTool(
        task=task,
        guard=PermissionGuardLite(tmp_workspace),
        lease_manager=LeaseManager(tmp_workspace),
        agent_id="agent-1",
        runtime_state={
            "run_id": "run-test",
            "event_sequence": 0,
            "trace_events": [],
        },
        counters=WorkerRuntimeCounters(),
    )


def test_file_snapshot_read(tmp_workspace: Path):
    target = tmp_workspace / "src" / "snap.txt"
    target.write_text("hello", encoding="utf-8")
    snapshot = FileSnapshot.read(target)
    assert snapshot.path == str(target.resolve())
    assert snapshot.content == "hello"
    assert snapshot.content_hash != ""


def test_idempotent_write_returns_cached_result(write_tool: ScopedFileWriteTool, tmp_workspace: Path):
    context = ToolContext(tmp_workspace)
    path = "src/x.py"

    first = write_tool.execute(
        {"path": path, "content": "first\n", "idempotency_key": "k1"},
        context,
    )
    assert first.ok
    assert first.metadata.get("idempotency") == "miss"
    assert first.metadata.get("attempt") == 1
    assert (tmp_workspace / "src" / "x.py").read_text(encoding="utf-8") == "first\n"

    second = write_tool.execute(
        {"path": path, "content": "second\n", "idempotency_key": "k1"},
        context,
    )
    assert second.ok
    assert second.metadata.get("idempotency") == "hit"
    assert second.metadata.get("attempt") == 2
    # Side effect must not be repeated: content stays from the first call.
    assert (tmp_workspace / "src" / "x.py").read_text(encoding="utf-8") == "first\n"


def test_cas_conflict_includes_snapshot(write_tool: ScopedFileWriteTool, tmp_workspace: Path):
    target = tmp_workspace / "src" / "cas.txt"
    target.write_text("original", encoding="utf-8")
    snapshot = FileSnapshot.read(target)

    result = write_tool.execute(
        {
            "path": "src/cas.txt",
            "content": "new",
            "expected_hash": "wrong-hash",
        },
        ToolContext(tmp_workspace),
    )
    assert not result.ok
    assert result.error_code == "cas_conflict"
    assert result.metadata["snapshot"]["content_hash"] == snapshot.content_hash
    # File must not be overwritten.
    assert target.read_text(encoding="utf-8") == "original"
