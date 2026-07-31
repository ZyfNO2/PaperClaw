from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.academic_frozen_inventory import resolve_frozen_sources


def test_frozen_sources_resolve_by_hash_not_filename(tmp_path: Path) -> None:
    source = tmp_path / "renamed.pdf"
    source.write_bytes(b"%PDF-real-paper")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    entries = [{"entry_id": "paper-1", "file_sha256": digest}]
    frozen = {
        "papers": [{"blind_id": "P01", "entry_id": "paper-1", "file_sha256": digest}]
    }

    resolved = resolve_frozen_sources(tmp_path, entries, frozen)
    assert resolved[0][2] == source


def test_frozen_sources_fail_closed_on_manifest_or_corpus_drift(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-real-paper")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    frozen = {
        "papers": [{"blind_id": "P01", "entry_id": "paper-1", "file_sha256": digest}]
    }
    with pytest.raises(ValueError, match="identity drift"):
        resolve_frozen_sources(
            tmp_path,
            [{"entry_id": "paper-1", "file_sha256": "0" * 64}],
            frozen,
        )

    source.unlink()
    with pytest.raises(FileNotFoundError, match="P01"):
        resolve_frozen_sources(
            tmp_path,
            [{"entry_id": "paper-1", "file_sha256": digest}],
            frozen,
        )
