from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path

from .state import HistoryEntry
from .verification import TaskClaim, VerificationCheck, VerificationEvidence, VerificationPlan, VerificationResult


def build_verification_plan(shared: dict) -> VerificationPlan:
    """Create the smallest deterministic verification plan from runtime facts.

    v0.02 starts with evidence we already control locally: written files, edited files, and whether a relevant
    verification command ran after the last write. This keeps Verify objective and bounded before Reflection exists.
    """

    claims: list[TaskClaim] = []
    checks: list[VerificationCheck] = []
    seen_paths: set[str] = set()
    latest_content_check_by_path: dict[str, tuple[TaskClaim, VerificationCheck]] = {}
    latest_hash_check_by_path: dict[str, tuple[TaskClaim, VerificationCheck]] = {}
    for entry in shared["history"]:
        if entry.tool == "file_write" and entry.result.ok:
            path = entry.arguments["path"]
            if path not in seen_paths:
                claim_id = f"claim-file-exists:{path}"
                claims.append(TaskClaim(claim_id, f"{path} exists inside the workspace", True, True, "inferred"))
                checks.append(VerificationCheck(f"check-file-exists:{path}", [claim_id], "file_exists", {"path": path}, True))
                seen_paths.add(path)
            content_claim_id = f"claim-file-contains:{path}:{entry.step}"
            latest_content_check_by_path[path] = (
                TaskClaim(content_claim_id, f"{path} contains the last written content from step {entry.step}", True, True, "inferred"),
                VerificationCheck(
                    f"check-file-contains:{path}:{entry.step}",
                    [content_claim_id],
                    "file_contains",
                    {"path": path, "substring": entry.arguments["content"]},
                    True,
                ),
            )
            hash_claim_id = f"claim-file-hash:{path}:{entry.step}"
            latest_hash_check_by_path[path] = (
                TaskClaim(hash_claim_id, f"{path} still matches the exact file content written at step {entry.step}", True, True, "inferred"),
                VerificationCheck(
                    f"check-file-hash:{path}:{entry.step}",
                    [hash_claim_id],
                    "file_hash",
                    {"path": path, "sha256": _content_sha256_for_file_write(entry.arguments["content"])},
                    True,
                ),
            )
        if entry.tool == "file_edit" and entry.result.ok:
            path = entry.arguments["path"]
            if path not in seen_paths:
                claim_id = f"claim-file-exists:{path}"
                claims.append(TaskClaim(claim_id, f"{path} exists inside the workspace", True, True, "inferred"))
                checks.append(VerificationCheck(f"check-file-exists:{path}", [claim_id], "file_exists", {"path": path}, True))
                seen_paths.add(path)
            content_claim_id = f"claim-edit-applied:{path}:{entry.step}"
            latest_content_check_by_path[path] = (
                TaskClaim(content_claim_id, f"{path} contains the edited content from step {entry.step}", True, True, "inferred"),
                VerificationCheck(
                    f"check-file-contains:{path}:{entry.step}",
                    [content_claim_id],
                    "file_contains",
                    {"path": path, "substring": entry.arguments["new_text"]},
                    True,
                ),
            )
            latest_hash_check_by_path.pop(path, None)

    for claim, check in latest_content_check_by_path.values():
        claims.append(claim)
        checks.append(check)
    for claim, check in latest_hash_check_by_path.values():
        claims.append(claim)
        checks.append(check)

    # Only require a post-write verification command when the task actually
    # performed write operations. A read-only task (file_read / grep / bash for
    # inspection only) has no writes to verify, so demanding a "verification
    # command after the last write" would always fail and block all read-only
    # Workers under the default Verify Gate.
    if seen_paths:
        command_claim_id = "claim-verification-command"
        claims.append(TaskClaim(command_claim_id, "a relevant verification command ran after the last write and reported success", True, True, "project_rule"))
        checks.append(VerificationCheck("check-verification-command", [command_claim_id], "history", {}, True))
    return VerificationPlan(claims, checks, "runtime-history", shared["step_count"])


def execute_verification_plan(shared: dict, plan: VerificationPlan) -> VerificationResult:
    """Run deterministic verification checks without modifying the workspace."""

    evidence: list[VerificationEvidence] = []
    passed_claim_ids: set[str] = set()
    failed_claim_ids: set[str] = set()
    uncovered_claim_ids: set[str] = set()

    # Only track post-write bash verification when the task actually wrote
    # files. Read-only tasks have no "last write" to verify after, so
    # verified_after_last_write must be True to avoid blocking them.
    has_writes = any(entry.tool in {"file_write", "file_edit"} and entry.result.ok for entry in shared["history"])
    if has_writes:
        last_write_step = max((entry.step for entry in shared["history"] if entry.tool in {"file_write", "file_edit"} and entry.result.ok), default=0)
        relevant_bash = _find_latest_relevant_bash(shared["history"], last_write_step)
        verified_after_last_write = relevant_bash is not None
    else:
        last_write_step = 0
        relevant_bash = None
        verified_after_last_write = True

    for check in plan.checks:
        if check.check_type == "file_exists":
            status, observed = _check_file_exists(shared["workspace"], check.arguments["path"])
            ev = VerificationEvidence(_next_evidence_id(evidence), check.check_id, status, observed, "file_read", None, None, datetime.now(timezone.utc))
        elif check.check_type == "file_contains":
            status, observed = _check_file_contains(shared["workspace"], check.arguments["path"], check.arguments["substring"])
            ev = VerificationEvidence(_next_evidence_id(evidence), check.check_id, status, observed, "file_read", None, None, datetime.now(timezone.utc))
        elif check.check_type == "file_hash":
            status, observed = _check_file_hash(shared["workspace"], check.arguments["path"], check.arguments["sha256"])
            ev = VerificationEvidence(_next_evidence_id(evidence), check.check_id, status, observed, "file_read", None, None, datetime.now(timezone.utc))
        elif check.check_type == "history":
            if relevant_bash is None:
                ev = VerificationEvidence(
                    _next_evidence_id(evidence),
                    check.check_id,
                    "failed",
                    "no relevant verification command was found after the last write",
                    "bash",
                    None,
                    None,
                    datetime.now(timezone.utc),
                )
            else:
                summary = summarize_command_result(relevant_bash)
                ev = VerificationEvidence(
                    _next_evidence_id(evidence),
                    check.check_id,
                    "passed" if relevant_bash.result.ok else "failed",
                    json.dumps(summary, ensure_ascii=False),
                    "bash",
                    relevant_bash.step,
                    relevant_bash.result.metadata.get("exit_code"),
                    datetime.now(timezone.utc),
                )
        else:
            ev = VerificationEvidence(_next_evidence_id(evidence), check.check_id, "error", f"unsupported check type: {check.check_type}", None, None, None, datetime.now(timezone.utc))
        evidence.append(ev)
        target = passed_claim_ids if ev.status == "passed" else failed_claim_ids
        target.update(check.claim_ids)

    for claim in plan.task_claims:
        if claim.required and claim.claim_id not in passed_claim_ids and claim.claim_id not in failed_claim_ids:
            uncovered_claim_ids.add(claim.claim_id)

    if failed_claim_ids:
        status = "failed"
    elif uncovered_claim_ids or not verified_after_last_write:
        status = "incomplete"
    else:
        status = "passed"
    return VerificationResult(
        status=status,
        checks=evidence,
        passed_claim_ids=sorted(passed_claim_ids),
        failed_claim_ids=sorted(failed_claim_ids),
        uncovered_claim_ids=sorted(uncovered_claim_ids),
        verified_after_last_write=verified_after_last_write,
        summary=_build_summary(status, evidence, verified_after_last_write),
    )


def _check_file_exists(workspace: Path, relative_path: str) -> tuple[str, str]:
    path = (workspace / relative_path).resolve()
    if path.exists() and path.is_file():
        return "passed", f"{relative_path} exists"
    return "failed", f"{relative_path} does not exist"


def _check_file_contains(workspace: Path, relative_path: str, substring: str) -> tuple[str, str]:
    path = (workspace / relative_path).resolve()
    if not path.exists():
        return "failed", f"{relative_path} does not exist"
    text = path.read_text(encoding="utf-8", errors="strict")
    if substring in text:
        return "passed", f"{relative_path} contains expected content"
    return "failed", f"{relative_path} is missing expected content"


def _check_file_hash(workspace: Path, relative_path: str, expected_sha256: str) -> tuple[str, str]:
    path = (workspace / relative_path).resolve()
    if not path.exists():
        return "failed", f"{relative_path} does not exist"
    actual_sha256 = sha256(path.read_bytes()).hexdigest()
    if actual_sha256 == expected_sha256:
        return "passed", f"{relative_path} sha256 matches expected content"
    return "failed", f"{relative_path} sha256 mismatch: expected {expected_sha256}, got {actual_sha256}"


def _content_sha256_for_file_write(content: str) -> str:
    """Reproduce the current FileWriteTool newline semantics before hashing.

    `Path.write_text()` uses text-mode newline translation. Verify mirrors that behavior so a hash claim describes the
    exact bytes the runtime wrote, not only the Python string before platform newline normalization.
    """

    normalized = content.replace("\r\n", "\n")
    if os.linesep != "\n":
        normalized = normalized.replace("\n", os.linesep)
    return sha256(normalized.encode("utf-8")).hexdigest()


def _find_latest_relevant_bash(history: list[HistoryEntry], last_write_step: int) -> HistoryEntry | None:
    touched_files = [Path(entry.arguments["path"]).name for entry in history if entry.tool in {"file_write", "file_edit"} and entry.result.ok]
    for entry in reversed(history):
        if entry.tool != "bash" or entry.step < last_write_step:
            continue
        command = entry.arguments["command"]
        if _command_looks_relevant(command, touched_files):
            return entry
    return None


def _command_looks_relevant(command: str, touched_files: list[str]) -> bool:
    normalized = command.lower()
    if "pytest" in normalized:
        return True
    if any(file_name.lower() in normalized for file_name in touched_files):
        return True
    # Reject generic success commands like "echo ok" that do not exercise the modified artifact.
    return False


def _next_evidence_id(existing: list[VerificationEvidence]) -> str:
    return f"ev-{len(existing) + 1}"


def _build_summary(status: str, evidence: list[VerificationEvidence], verified_after_last_write: bool) -> str:
    parts = [f"verification status={status}", f"checks={len(evidence)}"]
    if not verified_after_last_write:
        parts.append("no relevant verification command after last write")
    return "; ".join(parts)


def summarize_command_result(entry: HistoryEntry) -> dict:
    """Extract a stable command summary for audit-friendly verification evidence.

    The summary preserves raw exit/timing/truncation facts and adds a lightweight pytest parser when applicable. If the
    parser cannot confidently infer counts, we keep only the raw facts instead of inventing numbers.
    """

    metadata = entry.result.metadata
    summary = {
        "command": metadata.get("command", entry.arguments["command"]),
        "command_class": metadata.get("command_class", "shell"),
        "cwd": metadata.get("cwd"),
        "exit_code": metadata.get("exit_code"),
        "timed_out": metadata.get("timed_out", False),
        "duration_ms": metadata.get("duration_ms"),
        "started_at": metadata.get("started_at"),
        "finished_at": metadata.get("finished_at"),
        "truncated": metadata.get("truncated", False),
        "ok": entry.result.ok,
    }
    if summary["command_class"] == "pytest":
        summary["pytest"] = parse_pytest_summary(entry.result.output)
    return summary


def parse_pytest_summary(output: str) -> dict:
    """Best-effort pytest footer parser.

    v0.02 only needs small deterministic stats for verify evidence. When pytest output is incomplete or truncated we
    keep nullable counts and a short list of failed test names instead of guessing.
    """

    summary = {
        "passed_count": None,
        "failed_count": None,
        "skipped_count": None,
        "duration_seconds": None,
        "failed_test_names": [],
    }
    footer_match = re.search(r"=+\s*(.*?)\s+in\s+([0-9.]+)s\s*=+", output, re.IGNORECASE | re.DOTALL)
    simple_match = re.search(r"(?m)^\s*((?:\d+\s+\w+(?:,\s*)?)*)\s+in\s+([0-9.]+)s\s*$", output)
    match = footer_match or simple_match
    if match:
        counts_part, duration = match.groups()
        summary["duration_seconds"] = float(duration)
        for key in ("passed", "failed", "skipped"):
            count_match = re.search(rf"(\d+)\s+{key}", counts_part)
            if count_match:
                summary[f"{key}_count"] = int(count_match.group(1))
    for line in output.splitlines():
        if "::" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("FAILED "):
            summary["failed_test_names"].append(stripped.split()[1])
        elif stripped.endswith(" FAILED") or " FAILED " in stripped:
            summary["failed_test_names"].append(stripped.split()[0])
        if len(summary["failed_test_names"]) >= 10:
            break
    return summary
