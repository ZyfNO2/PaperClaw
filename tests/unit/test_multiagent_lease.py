"""Tests for FileLease manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.multiagent.lease import LeaseManager


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path


def test_lease_granted(tmp_workspace: Path):
    mgr = LeaseManager(tmp_workspace)
    result = mgr.acquire("src/a.py", "agent-1", "task-1")
    assert result.decision.value == "granted"
    assert result.lease is not None


def test_lease_conflict(tmp_workspace: Path):
    mgr = LeaseManager(tmp_workspace)
    mgr.acquire("src/a.py", "agent-1", "task-1")
    result = mgr.acquire("src/a.py", "agent-2", "task-2")
    assert result.decision.value == "conflict"


def test_same_task_already_owns(tmp_workspace: Path):
    mgr = LeaseManager(tmp_workspace)
    mgr.acquire("src/a.py", "agent-1", "task-1")
    result = mgr.acquire("src/a.py", "agent-1", "task-1")
    assert result.decision.value == "already_owns"


def test_outside_workspace_denied(tmp_workspace: Path):
    mgr = LeaseManager(tmp_workspace)
    result = mgr.acquire("../escape.py", "agent-1", "task-1")
    assert result.decision.value == "outside_workspace"


def test_release_all_for_task(tmp_workspace: Path):
    mgr = LeaseManager(tmp_workspace)
    mgr.acquire("src/a.py", "agent-1", "task-1")
    mgr.acquire("src/b.py", "agent-1", "task-1")
    released = mgr.release_all_for_task("task-1")
    assert len(released) == 2
    assert mgr.owner("src/a.py") is None
