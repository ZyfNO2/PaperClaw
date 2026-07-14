from pathlib import Path

import pytest

from paperclaw.tools.base import ToolContext, safe_execute
from paperclaw.tools.file_edit import FileEditTool
from paperclaw.tools.file_read import FileReadTool
from paperclaw.tools.file_write import FileWriteTool


def test_read_range_and_truncation(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\ntwo\nthree", encoding="utf-8")
    result = safe_execute(FileReadTool(), {"path": "a.txt", "start_line": 2, "end_line": 3}, ToolContext(tmp_path, 20))
    assert result.ok and "2: two" in result.output and result.metadata["truncated"] is False


def test_write_create_and_refuse_overwrite(tmp_path: Path) -> None:
    tool = FileWriteTool()
    first = safe_execute(tool, {"path": "a.txt", "content": "hello"}, ToolContext(tmp_path))
    second = safe_execute(tool, {"path": "a.txt", "content": "bad"}, ToolContext(tmp_path))
    assert first.ok and not second.ok and second.error_code == "conflict"
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_edit_requires_unique_match(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("x x", encoding="utf-8")
    denied = safe_execute(FileEditTool(), {"path": "a.txt", "old_text": "x", "new_text": "y"}, ToolContext(tmp_path))
    assert not denied.ok and path.read_text() == "x x"
    accepted = safe_execute(FileEditTool(), {"path": "a.txt", "old_text": "x x", "new_text": "y"}, ToolContext(tmp_path))
    assert accepted.ok and path.read_text() == "y"


def test_path_escape_is_denied(tmp_path: Path) -> None:
    result = safe_execute(FileReadTool(), {"path": "../outside.txt"}, ToolContext(tmp_path))
    assert not result.ok and result.error_code == "validation_error"


def test_symlink_escape_is_denied(tmp_path: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.txt").write_text("secret")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    result = safe_execute(FileReadTool(), {"path": "link/secret.txt"}, ToolContext(tmp_path))
    assert not result.ok
