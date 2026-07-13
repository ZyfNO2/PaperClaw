"""Tests for PermissionGuard Lite."""

from __future__ import annotations

from pathlib import Path

from paperclaw.multiagent.permissions import PermissionGuardLite


def test_denies_tool_not_in_allowed():
    guard = PermissionGuardLite(Path("/tmp"))
    check = guard.check("bash", {"command": "echo ok"}, [], [], ["file_read"])
    assert check.decision.value == "deny"
    assert "not in task allowed_tools" in check.reason


def test_denies_path_escape():
    guard = PermissionGuardLite(Path("/tmp"))
    check = guard.check("file_write", {"path": "../escape"}, ["."], ["."], ["file_write"])
    assert check.decision.value == "deny"
    assert "escapes" in check.reason


def test_denies_bash_install():
    guard = PermissionGuardLite(Path("/tmp"))
    check = guard.check("bash", {"command": "pip install x"}, [], [], ["bash"])
    assert check.decision.value == "deny"


def test_allows_safe_bash():
    guard = PermissionGuardLite(Path("/tmp"))
    check = guard.check("bash", {"command": "echo hello"}, [], [], ["bash"])
    assert check.decision.value == "allow"


def test_allows_read_in_scope():
    guard = PermissionGuardLite(Path("/tmp"))
    check = guard.check("file_read", {"path": "src/main.py"}, ["src"], [], ["file_read"])
    assert check.decision.value == "allow"
