#!/usr/bin/env python3
"""PaperClaw Stop hook：检查当前 SOP checkbox 与交接物完整性。

行为：
1. 在 ``Plan/`` 下递归识别 ``PaperClaw_vX.Y*SOP`` 风格的正式或草案 SOP；
2. 若近期 commit 和工作树都不处于 SOP 上下文，静默退出；
3. 统计当前 SOP 的 ``- [ ]`` / ``- [x]``；
4. 检查对应 ``artifacts/vX_YY/`` 交接物；
5. 只输出证据摘要，始终非阻断，不联网，也不修改项目文件。

Hook 只是完成度提醒，不能替代测试、Trace、真实模型或人工演示。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta

REPO = Path(__file__).resolve().parents[2]
PLAN_DIR = REPO / "Plan"
ARTIFACTS_DIR = REPO / "artifacts"
CACHE_PATH = Path(__file__).parent / "_sop_completion_state.json"

# 强制 UTF-8 输出, 避免 Windows GBK 把中文 stderr 吞掉
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def _ascii_safe(text: str) -> str:
    """非 ASCII 字符换成 \\xNN 转义, 保证 Stop hook 框架收到输出."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _emit(msg: str = "") -> None:
    print(_ascii_safe(msg), file=sys.stderr)


def _git(*args: str, timeout: int = 5) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO, capture_output=True, text=True, timeout=timeout,
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


# ----------------- SOP 识别 -----------------

SOP_FILE_RE = re.compile(
    r"^PaperClaw_v(\d+)\.(\d+).*SOP(?:草案)?\.md$",
    re.IGNORECASE,
)
SOP_VERSION_IN_COMMIT_RE = re.compile(r"\bv\s?(\d+)\.(\d+)\b", re.IGNORECASE)
CHECKBOX_RE = re.compile(r"^\s*- \[( |x|X)\]\s*(.*)$")
INACTIVE_SOP_MARKERS = ("历史设计稿", "已停止执行", "归档")


def _is_inactive_sop(path: Path) -> bool:
    """Return True when a retained SOP file is explicitly archival."""
    try:
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:12])
    except (OSError, UnicodeError):
        return False
    return any(marker in head for marker in INACTIVE_SOP_MARKERS)


def _find_sop_files() -> list[Path]:
    """递归返回 Plan/ 下的 PaperClaw 正式或草案 SOP。"""
    out: list[Path] = []
    if not PLAN_DIR.exists():
        return out
    # os.walk 在 Windows 中文路径上比 pathlib glob 更稳定。
    for root, _, names in os.walk(PLAN_DIR):
        for name in names:
            if SOP_FILE_RE.match(name):
                path = Path(root) / name
                if not _is_inactive_sop(path):
                    out.append(path)
    return out


def _current_sop_by_mtime() -> tuple[Path | None, str | None]:
    """最近 7 天内 mtime 最新的 SOP 文件. 返回 (path, version_tag)."""
    cutoff = datetime.now() - timedelta(days=7)
    candidates: list[tuple[Path, float, str]] = []
    for p in _find_sop_files():
        m = SOP_FILE_RE.search(p.name)
        if not m:
            continue
        mtime = p.stat().st_mtime
        if datetime.fromtimestamp(mtime) < cutoff:
            continue
        tag = f"v{m.group(1)}.{m.group(2)}"
        candidates.append((p, mtime, tag))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0], candidates[0][2]


def _current_sop_from_commit() -> str | None:
    """从最近 10 个 commit message 里提取 PaperClaw vX.Y。"""
    log = _git("log", "-10", "--format=%s %b")
    for line in log.splitlines():
        m = SOP_VERSION_IN_COMMIT_RE.search(line)
        if m:
            return f"v{m.group(1)}.{m.group(2)}"
    return None


def _in_sop_context(current_tag: str | None, commit_tag: str | None) -> bool:
    """是否处于 SOP 上下文: commit 或最近改动文件命中任一即激活."""
    if commit_tag and current_tag and commit_tag == current_tag:
        return True
    # 最近 3 个 commit 触及正式或草案 SOP → 视为 SOP 上下文。
    touched = _git("log", "-3", "--name-only", "--format=", "--", "Plan/")
    for line in touched.splitlines():
        if SOP_FILE_RE.match(Path(line).name):
            return True
    # 当前 SOP 文件 24h 内被改动 → 视为上下文
    sop_path, _ = _current_sop_by_mtime()
    if sop_path:
        mtime = datetime.fromtimestamp(sop_path.stat().st_mtime)
        if (datetime.now() - mtime) < timedelta(hours=24):
            return True
    return False


# ----------------- checkbox 解析 -----------------

def _parse_checkboxes(sop_path: Path) -> dict:
    """解析 SOP 文档里所有 checkbox. 返回 {total, done, pending: [(line, text, section)]}."""
    pending: list[tuple[int, str, str]] = []
    done = 0
    total = 0
    current_section = "(preamble)"
    try:
        text = sop_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {"total": 0, "done": 0, "pending": []}
    for i, line in enumerate(text.splitlines(), 1):
        # 跟踪当前 section (## 或 ###)
        sec_m = re.match(r"^(#{2,4})\s+(.+)$", line)
        if sec_m:
            current_section = sec_m.group(2).strip()
        cb = CHECKBOX_RE.match(line)
        if cb:
            total += 1
            mark = cb.group(1).lower()
            text_content = cb.group(2).strip()
            if mark == "x":
                done += 1
            else:
                pending.append((i, text_content, current_section))
    return {"total": total, "done": done, "pending": pending}


# ----------------- 交接包产物检查 -----------------

# Per-version handoff manifests. Unknown future versions use the small generic
# MVP set instead of inheriting an old domain-specific package.
DEFAULT_HANDOFF_FILES = [
    "implementation_summary.md",
    "test_report.md",
    "known_limitations.md",
    "file_manifest.txt",
]

VERSION_HANDOFF_FILES: dict[str, list[str]] = {
    "v0.02": [
        "implementation_summary.md",
        "verification_contract.md",
        "test_report.md",
        "verify_reflection_trace.json",
        "failure_cases.md",
        "file_manifest.txt",
    ],
    "v0.03": [
        "implementation_summary.md",
        "multiagent_contract.md",
        "task_dag_examples.json",
        "collaboration_trace.json",
        "conflict_test_report.md",
        "reviewer_findings.json",
        "file_manifest.txt",
    ],
    "v0.04": [
        "test_report.md",
        "mvp_demo_trace.json",
        "known_limitations.md",
        "implementation_summary.md",
        "file_manifest.txt",
    ],
    "v0.05": [
        "query_engine_contract.md",
        "mvp_test_report.md",
        "mvp_demo_trace.json",
        "known_limitations.md",
        "file_manifest.txt",
    ],
    "v0.06": [
        "implementation_summary.md",
        "mvp_test_report.md",
        "mvp_demo_trace.json",
        "tui_boundary.md",
        "known_limitations.md",
    ],
}


def _handoff_files_for(version_tag: str) -> list[str]:
    return VERSION_HANDOFF_FILES.get(version_tag.lower(), DEFAULT_HANDOFF_FILES)


def _find_handoff_dirs(version_tag: str) -> list[Path]:
    """根据 vX.Y → artifacts/vX_YY/ 查找交接包目录。

    兼容根目录直接存放交接物，以及每个 work package 一个子目录。
    """
    m = re.match(r"v(\d+)\.(\d+)", version_tag, re.IGNORECASE)
    if not m:
        return []
    artifact_root = ARTIFACTS_DIR / f"v{m.group(1)}_{m.group(2)}"
    if not artifact_root.exists():
        return []
    expected_files = set(_handoff_files_for(version_tag))
    # 子目录必须包含至少一个该版本的清单文件才视为交接包 (排除 demo_workspace 等产物目录)
    subdirs = [
        p for p in artifact_root.iterdir()
        if p.is_dir() and p.name != "eval" and any((p / name).exists() for name in expected_files)
    ]
    # 若无子目录, 但根目录有任一清单文件 → 视为根目录本身是一个交接包
    if not subdirs and any((artifact_root / name).exists() for name in expected_files):
        return [artifact_root]
    return subdirs


def _check_handoff_completeness(handoff_dirs: list[Path], version_tag: str) -> dict:
    """每个交接包目录是否齐备产物文件. 根目录布局可缺 trace/metrics."""
    if not handoff_dirs:
        return {"has_handoff": False, "dirs": []}
    expected = _handoff_files_for(version_tag)
    result = []
    for d in handoff_dirs:
        present = [f for f in expected if (d / f).exists()]
        missing = [f for f in expected if not (d / f).exists()]
        result.append({
            "dir": d.name,
            "present": present,
            "missing": missing,
            "complete": not missing,
        })
    return {"has_handoff": True, "dirs": result}


# ----------------- 缓存 -----------------

def _load_cache() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(data: dict) -> None:
    try:
        CACHE_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ----------------- 主流程 -----------------

def main() -> int:
    if not (REPO / ".git").exists():
        return 0

    sop_path, current_tag = _current_sop_by_mtime()
    commit_tag = _current_sop_from_commit()

    # 不在 SOP 上下文 → 静默退出
    if not _in_sop_context(current_tag, commit_tag):
        _save_cache({"last_run": datetime.now().isoformat(), "in_context": False})
        return 0

    # 当前工作树最近修改的 SOP 优先，避免旧 commit tag 指向上一版本。
    target_tag = current_tag or commit_tag
    if not target_tag or not sop_path:
        _emit("  [SOP completion] in SOP context but no SOP file found; skip")
        return 0

    # 如果当前工作树没有明确的最近 SOP，再退回到 commit 提到的版本。
    if commit_tag and not current_tag:
        for p in _find_sop_files():
            m = SOP_FILE_RE.search(p.name)
            if m and f"v{m.group(1)}.{m.group(2)}" == commit_tag:
                sop_path = p
                target_tag = commit_tag
                break

    # 解析 checkbox
    cb = _parse_checkboxes(sop_path)

    # 查交接包
    handoff_dirs = _find_handoff_dirs(target_tag)
    handoff = _check_handoff_completeness(handoff_dirs, target_tag)

    # 汇总输出
    _emit("")
    _emit("=" * 70)
    _emit(f"  [SOP completion check] {target_tag}")
    _emit("=" * 70)
    _emit(f"  SOP file: {sop_path.relative_to(REPO)}")
    _emit(f"  Commit tag: {commit_tag or '(not in recent commits)'}")
    _emit("")

    # checkbox 部分
    _emit(f"  Checkbox: {cb['done']}/{cb['total']} done, {len(cb['pending'])} pending")
    if cb["pending"]:
        _emit("")
        _emit("  Pending items:")
        for i, (lineno, text, section) in enumerate(cb["pending"], 1):
            short = text[:100] + ("..." if len(text) > 100 else "")
            _emit(f"    {i}. [L{lineno} §{section}] {short}")
    _emit("")

    # 交接包部分
    if handoff["has_handoff"]:
        _emit(f"  Handoff packages under artifacts/{target_tag.lower().replace('.', '_')}/:")
        for d in handoff["dirs"]:
            mark = "OK" if d["complete"] else "!!"
            miss = ", ".join(d["missing"]) if d["missing"] else "complete"
            _emit(f"    [{mark}] {d['dir']}: {miss}")
    else:
        _emit(f"  Handoff packages: none under artifacts/{target_tag.lower().replace('.', '_')}/")
    _emit("")

    # 总结判定
    all_checkbox_done = cb["total"] > 0 and not cb["pending"]
    all_handoff_complete = (
        handoff["has_handoff"]
        and all(d["complete"] for d in handoff["dirs"])
    )

    if all_checkbox_done and all_handoff_complete:
        _emit(f"  >> {target_tag} SOP 全量完成 (all checkboxes ticked + handoff complete)")
    elif all_checkbox_done and not handoff["has_handoff"]:
        _emit(f"  >> {target_tag} SOP checkbox 全勾选, 但无交接包目录 — 确认是否需要生成")
    elif all_checkbox_done:
        _emit(f"  >> {target_tag} SOP checkbox 全勾选, 但交接包不齐 — 见上方 !! 标记")
    else:
        _emit(f"  >> {target_tag} SOP 仍有 {len(cb['pending'])} 项未勾选 — 在宣布完成前请处理这些项")

    _emit("=" * 70)
    _emit("")

    _save_cache({
        "last_run": datetime.now().isoformat(),
        "in_context": True,
        "tag": target_tag,
        "checkbox_done": cb["done"],
        "checkbox_total": cb["total"],
        "pending_count": len(cb["pending"]),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
