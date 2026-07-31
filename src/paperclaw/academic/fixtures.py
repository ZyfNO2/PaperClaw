"""Stable canonicalization for cross-repository REST fixture bytes."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_IDENTITY_KEYS = {
    "paper_id",
    "version_id",
    "object_id",
    "bundle_id",
    "trace_id",
    "generation_id",
    "index_generation_id",
    "source_hash",
    "asset_hash",
    "content_hash",
    "corpus_hash",
    "request_fingerprint",
    "model_fingerprint",
}


def canonicalize_retrieval_fixture(value: Any) -> Any:
    """Replace nondeterministic identities while preserving cross-field equality."""

    identities: dict[tuple[str, str], str] = {}

    def visit(item: Any, key: str | None = None) -> Any:
        if isinstance(item, dict):
            return {name: visit(child, name) for name, child in sorted(item.items())}
        if isinstance(item, list):
            child_key = "asset_hash" if key == "asset_hashes" else key
            return [visit(child, child_key) for child in item]
        if key == "content_sha256":
            key = "asset_hash"
        if key == "etag" and isinstance(item, str):
            return "<etag>"
        if key in _IDENTITY_KEYS and isinstance(item, str):
            identity = (key, item)
            if identity not in identities:
                identities[identity] = f"<{key}:{len(identities) + 1}>"
            return identities[identity]
        return item

    return visit(value)


def canonical_fixture_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            canonicalize_retrieval_fixture(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def fixture_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_fixture_bytes(value)).hexdigest()
