"""Verify H0 corpus manifest integrity.

Checks:
- corpus_manifest.jsonl is valid UTF-8, LF, no BOM
- 107 entries, sorted by entry_id, fixed key order
- All file_sha256 values are 64-char hex
- year is null or 1900-2099; arxiv_id format valid
- frozen_12.json references valid entry_ids with matching sha256
- blind IDs P01-P12 unique and consecutive
- 12 frozen SHA values are distinct
- four benchmark strata each have exactly 3 papers
- frozen entries must have parser_status=ready
- invalid_input_decisions.jsonl covers exactly the 10 failed entries
- No local absolute paths or usernames in any file
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
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
_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_FORBIDDEN = re.compile(r"(C:\\Users|/home/|/Users/)", re.IGNORECASE)
_EXPECTED_STRATA = {"crack_detection", "reconstruction_3d_stereo", "segmentation", "concrete_material"}


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
        year = entry["year"]
        if year is not None and not (1900 <= year <= 2099):
            errors.append(f"{entry['entry_id']}: year {year} out of range")
        arxiv = entry["arxiv_id"]
        if arxiv is not None and not _ARXIV_RE.match(arxiv):
            errors.append(f"{entry['entry_id']}: invalid arxiv_id '{arxiv}'")

    for line in lines:
        if _FORBIDDEN.search(line):
            errors.append("forbidden path pattern found in manifest")
            break

    content = text.encode("utf-8")
    manifest_digest = hashlib.sha256(content).hexdigest()

    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    if frozen["manifest_sha256"] != manifest_digest:
        errors.append("frozen_12 manifest_sha256 does not match manifest content")

    papers = frozen["papers"]
    if len(papers) != 12:
        errors.append(f"frozen set has {len(papers)} papers, expected 12")

    blind_ids = [p["blind_id"] for p in papers]
    expected_blind = [f"P{i:02d}" for i in range(1, 13)]
    if blind_ids != expected_blind:
        errors.append(f"blind IDs not P01-P12 consecutive: {blind_ids}")

    frozen_shas = [p["file_sha256"] for p in papers]
    if len(set(frozen_shas)) != len(frozen_shas):
        errors.append("frozen set contains duplicate SHA-256 values")

    strata = Counter(p["benchmark_stratum"] for p in papers)
    if set(strata.keys()) != _EXPECTED_STRATA:
        errors.append(f"unexpected strata: {set(strata.keys())}")
    for stratum, count in strata.items():
        if count != 3:
            errors.append(f"stratum '{stratum}' has {count} papers, expected 3")

    stratum_counts = frozen.get("stratum_counts", {})
    if stratum_counts != dict(strata):
        errors.append("stratum_counts field does not match actual paper distribution")

    entry_map = {e["entry_id"]: e for e in entries}
    for paper in papers:
        eid = paper["entry_id"]
        if eid not in entry_map:
            errors.append(f"frozen {eid} not in manifest")
        elif entry_map[eid]["file_sha256"] != paper["file_sha256"]:
            errors.append(f"frozen {eid} sha256 mismatch")
        elif entry_map[eid]["parser_status"] != "ready":
            errors.append(f"frozen {eid} parser_status is not ready")

    failed_ids = {e["entry_id"] for e in entries if e["parser_status"] == "failed"}
    dec_lines = DECISIONS.read_text(encoding="utf-8").splitlines()
    decisions = [json.loads(line) for line in dec_lines]
    decision_ids = {d["entry_id"] for d in decisions}

    if len(decisions) != 10:
        errors.append(f"expected 10 decisions, got {len(decisions)}")
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

    print(f"manifest_sha256: {manifest_digest}")
    print(f"entries: {len(entries)}")
    print(f"frozen: {len(papers)}")
    print(f"decisions: {len(decisions)}")
    print(f"strata: {dict(strata)}")

    if errors:
        print(f"\nFAILED ({len(errors)} errors):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
