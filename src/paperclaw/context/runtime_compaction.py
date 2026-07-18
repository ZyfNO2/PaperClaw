"""Deterministic in-run history compaction.

The runtime keeps the full structured ``HistoryEntry`` list for replay and audit,
but model prompts switch to a compacted view once the history crosses a bounded
threshold. Foundational instructions, task text, long memory and user profile are
outside this module and therefore never summarized here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import ceil
from typing import Any


@dataclass(frozen=True)
class RuntimeCompactionPolicy:
    trigger_tokens: int = 3_500
    target_tokens: int = 2_200
    recent_entries: int = 6
    max_argument_chars: int = 320
    max_output_excerpt_chars: int = 320
    max_recent_argument_chars: int = 2_000
    max_recent_output_chars: int = 4_000
    max_summary_chars: int = 7_000

    def __post_init__(self) -> None:
        for name, value in (
            ("trigger_tokens", self.trigger_tokens),
            ("target_tokens", self.target_tokens),
            ("recent_entries", self.recent_entries),
            ("max_argument_chars", self.max_argument_chars),
            ("max_output_excerpt_chars", self.max_output_excerpt_chars),
            ("max_recent_argument_chars", self.max_recent_argument_chars),
            ("max_recent_output_chars", self.max_recent_output_chars),
            ("max_summary_chars", self.max_summary_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.target_tokens >= self.trigger_tokens:
            raise ValueError("target_tokens must be smaller than trigger_tokens")


@dataclass(frozen=True)
class RuntimeHistoryView:
    compacted: bool
    full_history_json: str | None
    summary_json: str | None
    recent_history_json: str
    original_tokens: int
    rendered_tokens: int
    covered_steps: tuple[int, ...]
    recent_steps: tuple[int, ...]
    fingerprint: str
    changed: bool


def build_runtime_history_view(
    shared: dict[str, Any],
    *,
    policy: RuntimeCompactionPolicy | None = None,
) -> RuntimeHistoryView:
    resolved = policy or RuntimeCompactionPolicy()
    history = tuple(shared.get("history", ()))
    serialized = [entry.to_dict() for entry in history]
    full_json = json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))
    original_tokens = estimate_runtime_tokens(full_json)
    if original_tokens <= resolved.trigger_tokens or len(history) <= resolved.recent_entries:
        fingerprint = hashlib.sha256(full_json.encode("utf-8")).hexdigest()
        previous = shared.get("history_compaction") or {}
        changed = bool(previous) and previous.get("fingerprint") != fingerprint
        shared["history_compaction"] = {
            "compacted": False,
            "fingerprint": fingerprint,
            "covered_steps": [],
            "recent_steps": [int(item.step) for item in history],
            "original_tokens": original_tokens,
            "rendered_tokens": original_tokens,
        }
        return RuntimeHistoryView(
            compacted=False,
            full_history_json=full_json,
            summary_json=None,
            recent_history_json="[]",
            original_tokens=original_tokens,
            rendered_tokens=original_tokens,
            covered_steps=(),
            recent_steps=tuple(int(item.step) for item in history),
            fingerprint=fingerprint,
            changed=changed,
        )

    old_entries = list(history[: -resolved.recent_entries])
    recent_entries = list(history[-resolved.recent_entries :])
    summary_payload, summary_json = _render_summary(old_entries, shared, resolved)
    recent_records, recent_json = _render_recent(recent_entries, resolved)
    rendered_tokens = estimate_runtime_tokens(summary_json + recent_json)

    while rendered_tokens > resolved.target_tokens and len(recent_entries) > 2:
        old_entries.append(recent_entries.pop(0))
        summary_payload, summary_json = _render_summary(old_entries, shared, resolved)
        recent_records, recent_json = _render_recent(recent_entries, resolved)
        rendered_tokens = estimate_runtime_tokens(summary_json + recent_json)

    covered_steps = tuple(int(entry.step) for entry in old_entries)
    recent_steps = tuple(int(entry.step) for entry in recent_entries)
    fingerprint_payload = {
        "summary": summary_payload,
        "recent": recent_records,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    previous = shared.get("history_compaction") or {}
    changed = previous.get("fingerprint") != fingerprint
    shared["history_compaction"] = {
        "compacted": True,
        "fingerprint": fingerprint,
        "covered_steps": list(covered_steps),
        "recent_steps": list(recent_steps),
        "original_tokens": original_tokens,
        "rendered_tokens": rendered_tokens,
        "method": "deterministic_structured_extract_v1",
    }
    return RuntimeHistoryView(
        compacted=True,
        full_history_json=None,
        summary_json=summary_json,
        recent_history_json=recent_json,
        original_tokens=original_tokens,
        rendered_tokens=rendered_tokens,
        covered_steps=covered_steps,
        recent_steps=recent_steps,
        fingerprint=fingerprint,
        changed=changed,
    )


def _render_summary(
    entries: list[Any],
    shared: dict[str, Any],
    policy: RuntimeCompactionPolicy,
) -> tuple[dict[str, Any], str]:
    payload = _summary_payload(entries, shared, policy)
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(rendered) > policy.max_summary_chars:
        payload["records"] = _fit_records(
            payload["records"], policy.max_summary_chars
        )
        payload["summary_truncated"] = True
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return payload, rendered


def _render_recent(
    entries: list[Any], policy: RuntimeCompactionPolicy
) -> tuple[list[dict[str, Any]], str]:
    records = [_recent_record(entry, policy) for entry in entries]
    return records, json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _summary_payload(
    entries: list[Any],
    shared: dict[str, Any],
    policy: RuntimeCompactionPolicy,
) -> dict[str, Any]:
    records = [_entry_record(entry, policy) for entry in entries]
    failures = [
        {
            "step": record["step"],
            "tool": record["tool"],
            "error_code": record["error_code"],
            "reason": record["reason"],
        }
        for record in records
        if not record["ok"]
    ]
    successful = [record["step"] for record in records if record["ok"]]
    tools = sorted({str(record["tool"]) for record in records})
    remaining_issues = [
        str(value)[:300]
        for value in shared.get("remaining_issues", [])
        if isinstance(value, str) and value.strip()
    ]
    return {
        "schema": "paperclaw.runtime_history_summary.v1",
        "method": "deterministic_structured_extract",
        "covered_steps": [int(entry.step) for entry in entries],
        "tools_used": tools,
        "successful_steps": successful,
        "failed_attempts": failures,
        "remaining_issues": remaining_issues,
        "records": records,
        "summary_truncated": False,
    }


def _entry_record(entry: Any, policy: RuntimeCompactionPolicy) -> dict[str, Any]:
    result = entry.result
    arguments = json.dumps(
        entry.arguments,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    output = str(result.output or "")
    return {
        "step": int(entry.step),
        "tool": str(entry.tool),
        "ok": bool(result.ok),
        "error_code": result.error_code,
        "reason": _clip(str(entry.reason), 240),
        "arguments_excerpt": _clip(arguments, policy.max_argument_chars),
        "argument_keys": sorted(str(key) for key in entry.arguments),
        "output_excerpt": _clip(output, policy.max_output_excerpt_chars),
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "metadata_keys": sorted(str(key) for key in result.metadata),
    }


def _recent_record(entry: Any, policy: RuntimeCompactionPolicy) -> dict[str, Any]:
    result = entry.result
    arguments = json.dumps(
        entry.arguments,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    output = str(result.output or "")
    return {
        "step": int(entry.step),
        "tool": str(entry.tool),
        "arguments": _clip(arguments, policy.max_recent_argument_chars),
        "arguments_truncated": len(arguments) > policy.max_recent_argument_chars,
        "reason": _clip(str(entry.reason), 500),
        "result": {
            "ok": bool(result.ok),
            "output": _clip(output, policy.max_recent_output_chars),
            "output_truncated": len(output) > policy.max_recent_output_chars,
            "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "error_code": result.error_code,
            "metadata": result.metadata,
        },
    }


def _fit_records(records: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    used = 0
    for record in reversed(records):
        rendered = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if kept and used + len(rendered) > max_chars:
            break
        kept.append(record)
        used += len(rendered)
    kept.reverse()
    return kept


def estimate_runtime_tokens(value: str) -> int:
    if not value:
        return 0
    return max(1, ceil(len(value.encode("utf-8")) / 4))


def _clip(value: str, limit: int) -> str:
    normalized = value.replace("\x00", "")
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "…"


__all__ = [
    "RuntimeCompactionPolicy",
    "RuntimeHistoryView",
    "build_runtime_history_view",
    "estimate_runtime_tokens",
]
