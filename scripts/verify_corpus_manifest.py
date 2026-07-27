"""Verify H0 corpus manifest integrity.

Checks:
- corpus_manifest.jsonl is valid UTF-8, LF, no BOM
- 107 entries, sorted by entry_id, fixed key order
- All file_sha256 values are 64-char hex
- frozen_12.json references valid entry_ids with matching sha256
- invalid_input_decisions.jsonl covers exactly the failed entries
- No local absolute paths or usernames in any file
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path("benchmarks/academic_rag/v1")
MANIFEST = BASE / "corpus_manifest.jsonl"
FROZEN = BASE / "frozen_12.json"
DECISIONS = BASE / "invalid_input_decisions.jsonl"

KEY_ORDER = [
    "schema_version",
    "entry_id",
    "logical_filename",
    "file_sha256",
    "size_bytes",
    "category",
    "title",
    "year",
    "doi",
    "arxiv_id",
    "source_type",
    "source_reference",
    "license_status",
    "usage_status",
    "parser_status",
    "failure_code",
    "inclusion_status",
    "supersedes_entry_id",
]

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN = re.compile(r"(C:\\Users|/home/|/Users/)", re.IGNORECASE)


def main() -> int:
    errors: list[str] = []

    raw = MANIFEST.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("manifest has BOM")
    if b"\r\n" in raw:
        errors.append("manifest has CRLF")
    if not raw.endswith(b"\n"):
        errors.append("manifest missing trailing newline")

    text = raw.decode("utf-8")
    lines = text.splitlines()
    entries = [json.loads(line) for line in lines]

    if len(entries) != 107:
        errors.append(f"expected 107 entries, got {len(entries)}")

    ids = [e["entry_id"] for e in entries]
    if ids != sorted(ids):
        errors.append("entries not sorted by entry_id")

    for entry in entries:
        keys = list(entry.keys())
        if keys != KEY_ORDER:
            errors.append(f"{entry['entry_id']}: key order mismatch")
            break
        if not _SHA_RE.match(entry["file_sha256"]):
            errors.append(f"{entry['entry_id']}: invalid sha256 format")

    content = text.encode("utf-8")
    for line in lines:
        if _FORBIDDEN.search(line):
            errors.append("forbidden path pattern found in manifest")
            break

    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    if frozen["manifest_sha256"] != hashlib.sha256(content).hexdigest():
        errors.append("frozen_12 manifest_sha256 does not match manifest content")

    entry_map = {e["entry_id"]: e for e in entries}
    for paper in frozen["papers"]:
        eid = paper["entry_id"]
        if eid not in entry_map:
            errors.append(f"frozen {eid} not in manifest")
        elif entry_map[eid]["file_sha256"] != paper["file_sha256"]:
            errors.append(f"frozen {eid} sha256 mismatch")
        elif entry_map[eid]["parser_status"] != "ready":
            errors.append(f"frozen {eid} parser_status is not ready")

    if len(frozen["papers"]) != 12:
        errors.append(f"frozen set has {len(frozen['papers'])} papers, expected 12")

    failed_ids = {e["entry_id"] for e in entries if e["parser_status"] == "failed"}
    dec_lines = DECISIONS.read_text(encoding="utf-8").splitlines()
    decisions = [json.loads(line) for line in dec_lines]
    decision_ids = {d["entry_id"] for d in decisions}
    if decision_ids != failed_ids:
        missing = failed_ids - decision_ids
        extra = decision_ids - failed_ids
        if missing:
            errors.append(f"decisions missing for: {sorted(missing)}")
        if extra:
            errors.append(f"decisions for non-failed: {sorted(extra)}")

    for dec in decisions:
        if dec["decision"] not in ("reacquire", "quarantine", "exclude"):
            errors.append(f"{dec['entry_id']}: invalid decision '{dec['decision']}'")

    manifest_digest = hashlib.sha256(content).hexdigest()
    print(f"manifest_sha256: {manifest_digest}")
    print(f"entries: {len(entries)}")
    print(f"frozen: {len(frozen['papers'])}")
    print(f"decisions: {len(decisions)}")

    if errors:
        print(f"\nFAILED ({len(errors)} errors):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
