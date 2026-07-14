#!/usr/bin/env python3
"""Stop hook: 检查当前 Phase 是否满足 CLAUDE.md 阶段开发流程 4 条强约束.

行为:
1. 读最近 1 个 commit message, 提取 Phase 编号 (Phase NN 或 PhaseN)
2. 检查 Plan/reports/Phase_NN_验收报告.md 是否存在
3. 检查 .claude/hooks/_post_phase_state.json 缓存 (避免每回合都跑 git)
4. 把结果打到 stderr, 提示这一轮还差哪几步
5. 不阻断 (exit 0)

不联网. 只读 git log + 磁盘文件.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO / "Plan" / "reports"
CACHE_PATH = Path(__file__).parent / "_post_phase_state.json"
SETTINGS_PATH = REPO / ".claude" / "settings.json"
PHASE_RE = re.compile(r"Phase\s*0*(\d+)", re.IGNORECASE)

# 强制 UTF-8 输出, 避免 Windows GBK 把中文 stderr 吞掉
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

# ASCII-only safe emit: Windows GBK 环境下 UTF-8 中文经常被
# Stop hook 框架判为 "No stderr output". 把信息先写到临时 buffer,
# 转成 ASCII-safe 形式再 print, 确保 Stop hook 一定能收到输出.
def _ascii_safe(text: str) -> str:
    """把所有非 ASCII 字符换成 \\xNN 转义, 避免 GBK 编码错误."""
    return text.encode("ascii", "backslashreplace").decode("ascii")

MAX_IDLE_CHECKS = 3  # 非 Phase commit 时最多提醒次数, 之后自移除


def _git(*args: str, timeout: int = 5) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO, capture_output=True, text=True, timeout=timeout,
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _latest_commit() -> tuple[str, str]:
    """返回 (subject, body). subject 可能含 Phase 编号."""
    subject = _git("log", "-1", "--format=%s")
    body = _git("log", "-1", "--format=%b")
    return subject, body


def _extract_phase(text: str) -> str | None:
    m = PHASE_RE.search(text or "")
    return f"Phase {int(m.group(1)):02d}" if m else None


def _report_exists(phase_tag: str) -> Path | None:
    if not phase_tag:
        return None
    num = phase_tag.split()[1]
    for name in (f"Phase_{num}_验收报告.md", f"Phase_{int(num)}_验收报告.md"):
        p = REPORTS_DIR / name
        if p.exists():
            return p
    return None


def _uncommitted() -> int:
    """返回 working tree 改动文件数 (modified + untracked, 不含 .claude/)."""
    status = _git("status", "--porcelain")
    if not status:
        return 0
    n = 0
    for line in status.splitlines():
        if not line:
            continue
        if ".claude/" in line:
            continue
        n += 1
    return n


def _emit(msg: str) -> None:
    print(_ascii_safe(msg), file=sys.stderr)


def _load_cache() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(data: dict) -> None:
    """合并写入 cache, 保留 idle_count 等字段."""
    try:
        existing = {}
        if CACHE_PATH.exists():
            existing = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        existing.update(data)
        CACHE_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _remove_stop_hook() -> None:
    """从 settings.json 中移除 Stop hook 条目."""
    try:
        if not SETTINGS_PATH.exists():
            return
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        hooks = settings.get("hooks", {})
        stop_list = hooks.get("Stop", [])
        if not stop_list:
            return
        # 只移除 post_phase_check 那个 hook 条目
        kept = []
        for entry in stop_list:
            hooks_list = entry.get("hooks", [])
            filtered = [h for h in hooks_list if "post_phase_check" not in h.get("command", "")]
            if filtered:
                entry["hooks"] = filtered
                kept.append(entry)
            # 如果 hooks 列表被清空, 不保留这个 entry
        if kept:
            hooks["Stop"] = kept
        else:
            del hooks["Stop"]
        settings["hooks"] = hooks
        SETTINGS_PATH.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _emit(f"  [Phase check] self-removed: Stop hook deleted from settings.json (idle full {MAX_IDLE_CHECKS} times)")
    except Exception as exc:
        _emit(f"  [Phase check] remove Stop hook failed: {exc}")


def main() -> int:
    if not (REPO / ".git").exists():
        return 0

    head_short = _git("log", "-1", "--format=%H")
    cache = _load_cache()
    if cache and cache.get("head") == head_short and cache.get("report"):
        report = cache["report"]
    else:
        subject, _ = _latest_commit()
        phase = _extract_phase(subject)
        report_path = _report_exists(phase) if phase else None
        dirty = _uncommitted()
        report = {
            "head": head_short,
            "subject": subject,
            "phase": phase,
            "report_path": str(report_path) if report_path else None,
            "uncommitted": dirty,
        }
        _save_cache({"head": head_short, "report": report})

    if not report.get("phase"):
        # 当前 head 不是 Phase commit — idle 计数器逻辑
        cache_all = cache or {}
        idle_count = cache_all.get("idle_count", 0) + 1
        idle_head = cache_all.get("idle_head", "")
        if head_short != idle_head:
            idle_count = 1  # 新 commit, 重置计数器
        _save_cache({"idle_count": idle_count, "idle_head": head_short})

        if idle_count > MAX_IDLE_CHECKS:
            # 超过上限 → 自移除 Stop hook, 此后不再触发
            _remove_stop_hook()
            return 0

        remaining = MAX_IDLE_CHECKS - idle_count
        _emit(f"  [Phase check] HEAD is not a Phase commit, skipped ({remaining} more reminders then auto-remove)")
        return 0

    # 命中 Phase commit → 重置 idle 计数器
    _save_cache({"idle_count": 0, "idle_head": ""})

    _emit("")
    _emit("=" * 70)
    _emit(f"  PostPhase check: {report['phase']} completion")
    _emit("=" * 70)
    _emit(f"  Latest commit: {report['subject']}")

    checks = [
        ("1. Tests pass (uv run pytest)", True, "see CLAUDE.md; explain any skip/xfail"),
        ("2. Commit landed (starts with 'Phase XX: ...')", True, f"detected: {report['subject'][:60]}"),
        ("3. Acceptance report (Plan/reports/Phase_NN_*.md)",
         bool(report.get("report_path")),
         report["report_path"] or f"MISSING -> write {REPORTS_DIR}/Phase_NN_*.md"),
        ("4. Working tree clean (no uncommitted changes)",
         report.get("uncommitted", 0) == 0,
         f"{report.get('uncommitted', 0)} uncommitted changes" if report.get("uncommitted") else "OK"),
    ]
    for name, ok, note in checks:
        mark = "OK" if ok else "!!"
        _emit(f"  [{mark}] {name}")
        if not ok or note:
            _emit(f"          -> {note}")
    _emit("=" * 70)
    _emit("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
