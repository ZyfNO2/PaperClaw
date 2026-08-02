"""Generate H0 corpus manifest for the 107-entry local PDF corpus.

Outputs benchmarks/academic_rag/v1/corpus_manifest.jsonl with fixed schema,
LF line endings, UTF-8, no BOM, sorted by entry_id, fixed JSON key order.
Does NOT write local absolute paths, usernames, or private directory structure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

CORPUS_ROOT = Path("data/paper_corpus")
OUTPUT = Path("benchmarks/academic_rag/v1/corpus_manifest.jsonl")

_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_ARXIV_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?!\d)")
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b", re.IGNORECASE)

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


def _derive_title(stem: str) -> str:
    title = re.sub(r"^\d{4}\.\d{4,5}[_\-\s]*", "", stem)
    title = re.sub(r"^\d{1,3}[_\-\s]+", "", title)
    title = title.replace("_", " ").replace("-", " ")
    title = re.sub(r"\s+", " ", title).strip()
    return title or stem


def _derive_year(stem: str) -> int | None:
    matches = _YEAR_RE.findall(stem)
    if matches:
        year = int(matches[-1])
        if 1900 <= year <= 2099:
            return year
    return None


def _derive_arxiv(stem: str) -> str | None:
    m = _ARXIV_RE.search(stem)
    return m.group(1) if m else None


def _check_pdf_valid(path: Path) -> tuple[str, str | None]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        return "failed", "invalid_pdf"
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw), strict=True)
        _ = reader.metadata
        pages = len(reader.pages)
        if pages == 0:
            return "failed", "zero_pages"
        return "ready", None
    except Exception:
        return "failed", "invalid_pdf"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=CORPUS_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    corpus = args.corpus.resolve(strict=True)
    output = args.output
    pdfs = sorted(corpus.rglob("*.pdf"), key=lambda p: p.as_posix().casefold())
    if not pdfs:
        print("ERROR: no PDFs found", file=sys.stderr)
        return 1

    entries: list[dict[str, Any]] = []
    for idx, pdf_path in enumerate(pdfs, start=1):
        relative = pdf_path.relative_to(corpus).as_posix()
        category = relative.split("/", 1)[0]
        raw = pdf_path.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
        stem = pdf_path.stem

        parser_status, failure_code = _check_pdf_valid(pdf_path)
        if parser_status == "failed":
            inclusion_status = "invalid"
        else:
            inclusion_status = "candidate"

        entry = {
            "schema_version": "academic-corpus.v1",
            "entry_id": f"paper-{idx:04d}",
            "logical_filename": pdf_path.name,
            "file_sha256": sha256,
            "size_bytes": len(raw),
            "category": category,
            "title": _derive_title(stem),
            "year": _derive_year(stem),
            "doi": None,
            "arxiv_id": _derive_arxiv(stem),
            "source_type": "user_supplied",
            "source_reference": None,
            "license_status": "unknown",
            "usage_status": "local_research_only",
            "parser_status": parser_status,
            "failure_code": failure_code,
            "inclusion_status": inclusion_status,
            "supersedes_entry_id": None,
        }
        entries.append(entry)

    entries.sort(key=lambda e: e["entry_id"])

    output.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for entry in entries:
        ordered = {k: entry[k] for k in KEY_ORDER}
        lines.append(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")))

    content = "\n".join(lines) + "\n"
    output.write_bytes(content.encode("utf-8"))

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    print(f"entries: {len(entries)}")
    print(f"output: {output.as_posix()}")
    print(f"manifest_sha256: {digest}")

    status_counts: dict[str, int] = {}
    for e in entries:
        status_counts[e["parser_status"]] = status_counts.get(e["parser_status"], 0) + 1
    print(f"parser_status: {status_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
