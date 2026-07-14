"""Addendum §7: vendored PocketFlow core integrity.

PF-12 (Vendor integrity): the vendored ``src/pocketflow/__init__.py`` blob
SHA must equal the value pinned in ``UPSTREAM.md``.

PF-13 (Import provenance): ``import pocketflow`` MUST resolve to the
project's vendored package, not to an externally-installed PyPI package.

PF-15 (Core untouched): PaperClaw Session / Checkpoint / Trace / Context
fields MUST NOT leak into the vendored core.

These checks run offline (no network). They protect the project from
accidental upgrades or external-package shadowing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Pinned values (must match UPSTREAM.md)
# ---------------------------------------------------------------------------

#: Upstream PocketFlow commit that produced the vendored snapshot.
EXPECTED_UPSTREAM_COMMIT = "43ef382bb0c9dae8167528618bb40f5a3f9a28a5"

#: Git blob SHA (``git hash-object``) of the vendored __init__.py.
EXPECTED_CORE_BLOB_SHA = "0b71858bfb9c0d8d02c5eb0b692d8b788af342e3"

#: Path to the vendored package inside this repo.
VENDORED_INIT_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "pocketflow" / "__init__.py"
)

#: Path to UPSTREAM.md (project root).
UPSTREAM_MD_PATH = (
    Path(__file__).resolve().parent.parent / "UPSTREAM.md"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_blob_sha(path: Path) -> str:
    """Compute the git blob SHA of ``path`` (``git hash-object`` equivalent).

    Git stores blobs as ``blob <size>\\0<content>`` SHA-1. We replicate the
    algorithm so the test does not need a git binary on PATH.

    Note on line endings: ``git hash-object`` applies the configured
    ``core.autocrlf`` filter (CRLF → LF on Windows) before hashing. We
    replicate that here so the test matches git's default behavior. Use
    ``git hash-object --no-filters`` to compare against the raw bytes.
    """
    raw = path.read_bytes()
    # Replicate core.autocrlf=true on Windows: CRLF → LF. Without this the
    # hash would differ from `git hash-object` on a checked-out file.
    content = raw.replace(b"\r\n", b"\n")
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _git_blob_sha_no_filters(path: Path) -> str:
    """Compute the git blob SHA without applying autocrlf filters.

    Equivalent to ``git hash-object --no-filters``. Useful for diffing
    against the raw file contents when debugging CRLF-related mismatches.
    """
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _file_content_sha256(path: Path) -> str:
    """SHA-256 of file contents, used as a secondary integrity check."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# PF-12: Vendor integrity
# ---------------------------------------------------------------------------


class TestVendorIntegrity:
    def test_vendored_init_blob_sha_matches_expected(self):
        """The vendored __init__.py must hash to the pinned blob SHA."""
        assert VENDORED_INIT_PATH.exists(), (
            f"vendored core missing at {VENDORED_INIT_PATH}"
        )
        actual = _git_blob_sha(VENDORED_INIT_PATH)
        assert actual == EXPECTED_CORE_BLOB_SHA, (
            f"vendored core blob SHA changed: expected {EXPECTED_CORE_BLOB_SHA}, "
            f"got {actual}. If this is an intentional upgrade, update "
            f"UPSTREAM.md and EXPECTED_CORE_BLOB_SHA together (Addendum §7.3)."
        )

    def test_upstream_md_records_pinned_values(self):
        """UPSTREAM.md must record the same commit and blob SHA used by tests."""
        assert UPSTREAM_MD_PATH.exists(), "UPSTREAM.md is missing"
        text = UPSTREAM_MD_PATH.read_text(encoding="utf-8")
        assert EXPECTED_UPSTREAM_COMMIT in text, (
            f"UPSTREAM.md does not pin upstream commit {EXPECTED_UPSTREAM_COMMIT}"
        )
        assert EXPECTED_CORE_BLOB_SHA in text, (
            f"UPSTREAM.md does not pin blob SHA {EXPECTED_CORE_BLOB_SHA}"
        )

    def test_vendored_core_does_not_contain_paperclaw_fields(self):
        """PF-15: PaperClaw-specific fields must not leak into vendored core.

        The vendored __init__.py is a verbatim copy of upstream PocketFlow.
        If PaperClaw Session / Checkpoint / Trace / Context / Permission /
        Tool fields appear here, the project has broken the boundary
        (Addendum §1).
        """
        text = VENDORED_INIT_PATH.read_text(encoding="utf-8")
        forbidden_markers = [
            "SessionEvent",
            "SessionService",
            "Checkpoint",
            "TaskState",
            "ContextItem",
            "ContextBuilder",
            "Permission",
            "IdempotencyLedger",
            "paperclaw.context",
            "paperclaw.runtime",
        ]
        for marker in forbidden_markers:
            assert marker not in text, (
                f"vendored core contains PaperClaw-specific marker {marker!r}; "
                f"the vendored core MUST stay free of PaperClaw Runtime fields"
            )


# ---------------------------------------------------------------------------
# PF-13: Import provenance
# ---------------------------------------------------------------------------


class TestImportProvenance:
    def test_import_pocketflow_loads_vendored_package(self):
        """``import pocketflow`` MUST resolve to this project's vendored
        package, not to an externally-installed PyPI version."""
        # Drop any cached pocketflow so we get a fresh import.
        sys.modules.pop("pocketflow", None)
        try:
            import pocketflow  # noqa: F401
        finally:
            pass

        # The loaded module's file must live under our src/pocketflow.
        module_file = getattr(pocketflow, "__file__", None)
        assert module_file is not None, "pocketflow module has no __file__"
        resolved = Path(module_file).resolve()
        vendored = VENDORED_INIT_PATH.resolve()
        assert resolved == vendored, (
            f"import pocketflow resolved to {resolved}, expected {vendored}. "
            f"An externally-installed 'pocketflow' package is shadowing the "
            f"vendored copy. Uninstall it or fix sys.path ordering."
        )

    def test_import_pocketflow_exposes_expected_classes(self):
        """Sanity: the vendored core exposes the public PocketFlow API."""
        import pocketflow

        for name in ("BaseNode", "Node", "Flow", "BatchNode", "BatchFlow"):
            assert hasattr(pocketflow, name), (
                f"pocketflow.{name} missing; vendored core may be corrupted"
            )


# ---------------------------------------------------------------------------
# Cross-check: blob SHA and content SHA256 are stable
# ---------------------------------------------------------------------------


class TestIntegrityStability:
    def test_blob_sha_is_stable_across_reads(self):
        """Reading the file twice produces the same blob SHA. Catches
        accidental file mutation between reads (e.g. by an editor)."""
        first = _git_blob_sha(VENDORED_INIT_PATH)
        second = _git_blob_sha(VENDORED_INIT_PATH)
        assert first == second
        assert first == EXPECTED_CORE_BLOB_SHA

    def test_content_sha256_is_recorded(self):
        """Secondary integrity check: a SHA-256 of the file content. This is
        not part of the pinned values in UPSTREAM.md but serves as a
        debugging aid when the blob SHA check fails."""
        sha = _file_content_sha256(VENDORED_INIT_PATH)
        # The SHA-256 is intentionally not pinned in UPSTREAM.md; we just
        # verify the function works and returns a 64-char hex string.
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)
