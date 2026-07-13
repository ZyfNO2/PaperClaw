"""Tests for scoped tool wrappers: idempotency, CAS, TOCTOU, and FileSnapshot."""

from __future__ import annotations

from unittest.mock import patch
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


def test_cas_conflict_event_routes_to_team_state(tmp_workspace: Path):
    """CAS conflict events must land in the shared team trace, not the Worker's local trace."""

    team_state = {"run_id": "run-team", "event_sequence": 0, "trace_events": []}
    task = AgentTask(
        task_id="t1",
        title="write",
        objective="write a file",
        acceptance_criteria=["file exists"],
        allowed_paths=["."],
        writable_paths=["src"],
        allowed_tools=["file_write"],
    )
    tool = ScopedFileWriteTool(
        task=task,
        guard=PermissionGuardLite(tmp_workspace),
        lease_manager=LeaseManager(tmp_workspace),
        agent_id="agent-1",
        runtime_state={
            "run_id": "run-worker",
            "_team_state": team_state,
            "event_sequence": 0,
            "trace_events": [],
        },
        counters=WorkerRuntimeCounters(),
    )
    target = tmp_workspace / "src" / "cas.txt"
    target.write_text("original", encoding="utf-8")

    result = tool.execute(
        {"path": "src/cas.txt", "content": "new", "expected_hash": "wrong-hash"},
        ToolContext(tmp_workspace),
    )
    assert not result.ok
    assert result.error_code == "cas_conflict"
    assert any(e["event_type"] == "tool.cas_conflict" for e in team_state["trace_events"])
    assert target.read_text(encoding="utf-8") == "original"


def test_external_edit_detected_by_expected_hash(write_tool: ScopedFileWriteTool, tmp_workspace: Path):
    """D7: a file modified externally between snapshot and write triggers a CAS conflict."""

    target = tmp_workspace / "src" / "external.txt"
    target.write_text("original", encoding="utf-8")
    snapshot = FileSnapshot.read(target)

    # Simulate an external edit after the snapshot was captured.
    target.write_text("tampered", encoding="utf-8")

    result = write_tool.execute(
        {
            "path": "src/external.txt",
            "content": "new",
            "expected_hash": snapshot.content_hash,
        },
        ToolContext(tmp_workspace),
    )
    assert not result.ok
    assert result.error_code == "cas_conflict"
    # The external edit must remain intact; we do not clobber it.
    assert target.read_text(encoding="utf-8") == "tampered"


def test_toctou_revalidation_denies_write_when_path_escapes(write_tool: ScopedFileWriteTool, tmp_workspace: Path):
    """D7: path revalidation right before write catches a symlink/junction switch."""

    target = tmp_workspace / "src" / "toctou.txt"
    target.write_text("safe", encoding="utf-8")

    call_count = 0
    original_resolve = write_tool._guard._resolve_path

    def _flaky_resolve(raw_path: str):
        nonlocal call_count
        call_count += 1
        # First call is from the permission check; second call is the TOCTOU
        # revalidation right before the write. Make the second one fail.
        if call_count == 2:
            return None
        return original_resolve(raw_path)

    with patch.object(write_tool._guard, "_resolve_path", side_effect=_flaky_resolve):
        result = write_tool.execute(
            {"path": "src/toctou.txt", "content": "malicious"},
            ToolContext(tmp_workspace),
        )

    assert not result.ok
    assert "escapes" in result.output.lower()
    assert target.read_text(encoding="utf-8") == "safe"
