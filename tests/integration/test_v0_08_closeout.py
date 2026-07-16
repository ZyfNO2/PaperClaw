from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOP = _REPOSITORY_ROOT / "Plan/PaperClaw_v0.08_Context_Orchestration_MVP_SOP.md"
_HOOK = _REPOSITORY_ROOT / ".claude/hooks/sop_completion_check.py"
_REQUIRED = (
    _REPOSITORY_ROOT / "artifacts/v0_08/implementation_summary.md",
    _REPOSITORY_ROOT / "artifacts/v0_08/test_report.md",
    _REPOSITORY_ROOT / "artifacts/v0_08/known_limitations.md",
    _REPOSITORY_ROOT / "artifacts/v0_08/file_manifest.txt",
    _REPOSITORY_ROOT / "artifacts/v0_08/mvp_demo_trace.json",
    _REPOSITORY_ROOT
    / "docs/handoff/PaperClaw_v0.08_Context_Orchestration_MVP_HANDOFF.md",
)


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("paperclaw_sop_hook", _HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v0_08_sop_and_handoff_package_are_complete() -> None:
    module = _load_hook_module()

    checkboxes = module._parse_checkboxes(_SOP)
    assert checkboxes["total"] > 0
    assert checkboxes["done"] == checkboxes["total"]
    assert checkboxes["pending"] == []
    assert all(path.is_file() and path.stat().st_size > 0 for path in _REQUIRED)

    handoff_dirs = module._find_handoff_dirs("v0.08")
    completeness = module._check_handoff_completeness(handoff_dirs, "v0.08")
    assert completeness["has_handoff"] is True
    assert all(item["complete"] for item in completeness["dirs"])


def test_sop_completion_hook_executes_successfully() -> None:
    completed = subprocess.run(
        [sys.executable, str(_HOOK)],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
