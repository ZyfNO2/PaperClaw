#!/usr/bin/env python3
"""Stop hook: 检查当前正在执行的 SOP 是否全量完成.

行为:
1. 识别"当前 SOP"——最近 7 天内 mtime 最新的 Plan/PaperAgent_Re*_SOP.md
2. 若不在 SOP 上下文 (最近 commit 无 SOP 编号 / 无 SOP 文件改动), 静默 exit 0
3. 扫该 SOP 文档里所有 `- [ ]` / `- [x]` checkbox, 统计未完成项
4. 查对应 artifacts/reN_M/<workpack>/ 交接包产物齐备性
5. 把结果打到 stderr, 非阻断 (exit 0)
6. 不联网. 只读 git log + 磁盘文件.

设计动机: 用户要求"在 SOP 结束时强制检查一遍是否全量完成", 避免自欺欺人.
与现有 post_phase_check.py (Phase 4 条强约束) 并列, 互不干扰.
"""

from __future__ import annotations

import json
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

SOP_FILE_RE = re.compile(r"(?:PaperAgent_Re|PaperClaw_v)(\d+)\.(\d+).*SOP\.md$", re.IGNORECASE)
SOP_VERSION_IN_COMMIT_RE = re.compile(r"(?:Re|v)\s?(\d+)\.(\d+)", re.IGNORECASE)
CHECKBOX_RE = re.compile(r"^\s*- \[( |x|X)\]\s*(.*)$")


def _find_sop_files() -> list[Path]:
    """所有 Plan/ 下的 PaperAgent_Re*_SOP.md (含 Arch/ Legcy/).

    Note: 不用 pathlib.glob — Windows 上 glob 对部分中文文件名匹配失败.
    改用 iterdir() + 正则过滤.
    """
    out: list[Path] = []
    name_re = re.compile(r"^(?:PaperAgent_Re|PaperClaw_v)\d+\.\d+.*SOP\.md$", re.IGNORECASE)
    for sub in ("", "Arch", "Legcy/reports"):
        base = PLAN_DIR / sub if sub else PLAN_DIR
        if not base.exists():
            continue
        try:
            for p in base.iterdir():
                if p.is_file() and name_re.match(p.name):
                    out.append(p)
        except (PermissionError, OSError):
            continue
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
    """从最近 10 个 commit message 里抽 ReN.M 版本号."""
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
    # 最近 3 个 commit 触及 SOP 文件 → 视为 SOP 上下文
    touched = _git("log", "-3", "--name-only", "--format=", "--", "Plan/")
    if touched and "SOP.md" in touched:
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

# Per-version handoff manifests. The list evolves with each SOP; the default
# set is kept for older ReN.M packages that were created before versioning.
DEFAULT_HANDOFF_FILES = [
    "implementation_summary.md",
    "verification_contract.md",
    "test_report.md",
    "verify_reflection_trace.json",
    "failure_cases.md",
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
}


def _handoff_files_for(version_tag: str) -> list[str]:
    return VERSION_HANDOFF_FILES.get(version_tag.lower(), DEFAULT_HANDOFF_FILES)


def _find_handoff_dirs(version_tag: str) -> list[Path]:
    """根据 ReN.M → artifacts/reN_M/ 下查找交接包子目录.

    兼容两种布局:
    a) artifacts/reN_M/<workpack>/  — 每个工作包一个子目录
    b) artifacts/reN_M/             — 根目录直接放 decision.md 等
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

    # PaperClaw 的 SOP 推进按当前工作树中最近修改的 SOP 为准，避免旧 commit tag 把检查错指到上一版。
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
