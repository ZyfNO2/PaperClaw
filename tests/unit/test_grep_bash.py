from pathlib import Path

from paperclaw.tools.bash import BashTool
from paperclaw.tools.base import ToolContext, safe_execute
from paperclaw.tools.grep import GrepTool


def test_grep_match_empty_and_invalid(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def hello():\n    pass\n", encoding="utf-8")
    match = safe_execute(GrepTool(), {"pattern": "hello", "glob": "*.py"}, ToolContext(tmp_path))
    empty = safe_execute(GrepTool(), {"pattern": "missing"}, ToolContext(tmp_path))
    invalid = safe_execute(GrepTool(), {"pattern": "["}, ToolContext(tmp_path))
    assert match.ok and "a.py:1" in match.output
    assert empty.ok and empty.metadata["matches"] == 0
    assert not invalid.ok and invalid.error_code == "validation_error"


def test_bash_success_failure_timeout_and_deny(tmp_path: Path) -> None:
    tool = BashTool()
    success = safe_execute(tool, {"command": "python -c \"print('OK')\""}, ToolContext(tmp_path))
    failed = safe_execute(tool, {"command": "python -c \"raise SystemExit(3)\""}, ToolContext(tmp_path))
    timed = safe_execute(tool, {"command": "python -c \"import time; time.sleep(2)\"", "timeout_seconds": 0.1}, ToolContext(tmp_path))
    denied = safe_execute(tool, {"command": "pip install example"}, ToolContext(tmp_path))
    assert success.ok and "OK" in success.output
    assert not failed.ok and failed.metadata["exit_code"] != 0
    assert not timed.ok and timed.error_code == "unknown_outcome"
    assert not denied.ok and denied.error_code == "validation_error"


def test_bash_timeout_kills_child_process_tree(tmp_path: Path) -> None:
    marker = tmp_path / "late.txt"
    script = tmp_path / "parent.py"
    child = "import time; time.sleep(2); open('late.txt','w').write('escaped')"
    script.write_text(f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\ntime.sleep(5)\n", encoding="utf-8")
    result = safe_execute(BashTool(), {"command": "python parent.py", "timeout_seconds": 0.2}, ToolContext(tmp_path))
    assert not result.ok and result.error_code == "unknown_outcome"
    import time
    time.sleep(2.2)
    assert not marker.exists()
