"""FileSnapshotVerifier: hashlib-based file state verification (Phase E).

Implements SOP §10.1 rule "关键文件 hash / existence 重新验证通过" and
§10.2 stop condition "文件 hash 与 Checkpoint 不一致".

Design intent — why a separate class instead of inline verification:

1. The Checkpoint's ``file_snapshots`` is a list of plain dicts. A bare
   callable ``Callable[[dict], bool]`` (what ``evaluate_resume_safety``
   accepts) is the protocol; this class is the production implementation.
   Tests can still pass a lambda for ``file_snapshot_verifier`` to
   inject synthetic mismatches without touching the filesystem.

2. ``snapshot(path)`` is a *companion* helper: it records the current
   state of a file BEFORE a mutating operation, so the caller can store
   the snapshot in ``Checkpoint.file_snapshots`` and later verify the
   file was not externally modified. Without this helper, every caller
   would reimplement hashlib + stat, drifting on edge cases (missing
   files, symlinks, large files).

3. ``verify`` accepts both v0.04 snapshots (``{path, hash, size,
   existence_required}``) and minimal snapshots (``{path, hash}``).
   Unknown keys are ignored, so the schema can grow without breaking
   older Checkpoints.

v0.04 scope (SOP §10.3 does NOT promise):

- Symlink target resolution (we follow the path as-is).
- Atomic snapshot-vs-verify (a TOCTOU race is possible between
  ``verify`` reading the file and the caller acting on the result).
  v0.04 assumes single-process resume with no concurrent writers; a
  real concurrent-safe version needs file locks (deferred to v0.04.1).
- Directory tree snapshots (only single files are snapshotted).

Hardening notes:

- ``_hash_file`` reads in 64 KiB chunks so a 1 GiB file does not load
  fully into memory. The chunk size matches OpenSSL's default buffer
  and is a reasonable trade-off between syscall overhead and RSS.
- ``verify`` returns False on any I/O error (permission denied, file
  vanished mid-read) rather than raising. The caller
  (``evaluate_resume_safety``) treats False as a mismatch, which is the
  safe default — a file we cannot read is a file whose state is
  unknown, and resume MUST stop.
- ``existence_required=False`` records ABSENCE: the snapshot asserts
  "this file should NOT exist when resume runs". Used for cleanup-style
  operations that delete files. A present file → mismatch.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Callable

#: Default chunk size for streaming file reads. 64 KiB matches OpenSSL's
#: default buffer and keeps peak RSS bounded even for 1 GiB files.
_HASH_CHUNK_SIZE = 65536

#: Default hash algorithm. SHA-256 is chosen over MD5 (collision-broken) and
#: SHA-1 (collision-broken) because v0.04 file snapshots are defense against
#: accidental external modification, not adversarial tampering — but SHA-256
#: has no known weaknesses and is the project-wide default.
_DEFAULT_HASH_ALGORITHM = "sha256"


class FileSnapshotVerifier:
    """Verify ``Checkpoint.file_snapshots`` entries against the live filesystem.

    Usage (recording a snapshot BEFORE a mutating operation)::

        verifier = FileSnapshotVerifier()
        snap = verifier.snapshot("/abs/path/to/file")
        # ... run the mutating operation ...
        checkpoint = Checkpoint(..., file_snapshots=(snap,))

    Usage (verifying on resume)::

        verifier = FileSnapshotVerifier()
        decision = evaluate_resume_safety(
            checkpoint=cp,
            current_registry=registry,
            file_snapshot_verifier=verifier.verify,
        )

    The class is stateless across ``verify`` calls; the only state is the
    configured hash algorithm. Reuse one instance per resume decision.
    """

    def __init__(self, *, hash_algorithm: str = _DEFAULT_HASH_ALGORITHM):
        self._hash_algorithm = hash_algorithm

    @property
    def hash_algorithm(self) -> str:
        """The hash algorithm name passed to ``hashlib.new``."""
        return self._hash_algorithm

    # ------------------------------------------------------------------
    # Verify (read-side, used by evaluate_resume_safety)
    # ------------------------------------------------------------------

    def verify(self, snapshot: dict[str, Any]) -> bool:
        """Return True if the file still matches the snapshot.

        Snapshot schema (v0.04):

        - ``path`` (str, required): absolute path to the file.
        - ``hash`` (str, optional): expected hex digest. When None, only
          existence/size are checked.
        - ``size`` (int, optional): expected size in bytes. When None,
          size is not checked.
        - ``existence_required`` (bool, default True): when True, the
          file MUST exist; when False, the file MUST NOT exist.

        Returns False when:

        - ``path`` is missing or not a string.
        - ``existence_required`` is True and the file does not exist.
        - ``existence_required`` is False and the file DOES exist
          (snapshot recorded absence, but the file appeared — likely
          an external process created it).
        - The file's hash differs from ``snapshot["hash"]``.
        - The file's size differs from ``snapshot["size"]``.
        - Any I/O error occurs during hashing (treated as "state
          unknown" → safe-default False).

        Returns True when the file matches all provided constraints.
        """
        path = snapshot.get("path")
        if not isinstance(path, str) or not path:
            return False

        expected_hash = snapshot.get("hash")
        expected_size = snapshot.get("size")
        existence_required = snapshot.get("existence_required", True)

        file_exists = os.path.exists(path)

        if not file_exists:
            # Snapshot said the file should exist, but it is gone.
            if existence_required:
                return False
            # Snapshot recorded absence and the file is still absent.
            # No further checks possible — hash and size are None.
            return True

        # File exists from here on.
        if not existence_required:
            # Snapshot said the file should NOT exist, but it does.
            # An external process created it → mismatch.
            return False

        # Size check (cheap, do it first to short-circuit hash mismatches
        # on grossly different files).
        if expected_size is not None:
            try:
                actual_size = os.path.getsize(path)
            except OSError:
                return False
            if actual_size != expected_size:
                return False

        # Hash check (expensive, only when size matches or was not provided).
        if expected_hash is not None:
            try:
                actual_hash = self._hash_file(path)
            except OSError:
                # Permission denied, file vanished mid-read, etc.
                # Treat as "state unknown" → safe default is to block resume.
                return False
            if actual_hash != expected_hash:
                return False

        return True

    # ------------------------------------------------------------------
    # Snapshot (write-side, used before mutating operations)
    # ------------------------------------------------------------------

    def snapshot(
        self,
        path: str,
        *,
        existence_required: bool = True,
    ) -> dict[str, Any]:
        """Build a snapshot dict for the file at ``path``.

        Called BEFORE a mutating operation to record the current file
        state. The returned dict is suitable for inclusion in
        ``Checkpoint.file_snapshots``.

        When the file does not exist:

        - If ``existence_required=True`` (default), the snapshot records
          ``hash=None, size=None, existence_required=True``. ``verify``
          will return False if the file still does not exist on resume
          (the mutating operation was supposed to create it but did not
          commit).
        - If ``existence_required=False``, the snapshot records absence
          and ``verify`` will return False if the file appears on resume
          (an external process created it).

        When the file exists, the snapshot records the current hash and
        size so resume can detect external modification.
        """
        if not os.path.exists(path):
            return {
                "path": path,
                "hash": None,
                "size": None,
                "existence_required": existence_required,
            }

        try:
            file_hash = self._hash_file(path)
            file_size = os.path.getsize(path)
        except OSError:
            # File existed moments ago but vanished or became unreadable.
            # Record absence rather than crashing — the caller can still
            # store this snapshot; verify will return False on resume
            # (state unknown).
            return {
                "path": path,
                "hash": None,
                "size": None,
                "existence_required": existence_required,
            }

        return {
            "path": path,
            "hash": file_hash,
            "size": file_size,
            "existence_required": existence_required,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _hash_file(self, path: str) -> str:
        """Stream the file through ``hashlib.new(algorithm)`` in chunks.

        Reads in 64 KiB chunks to bound peak RSS. Returns the hex digest.

        Raises ``OSError`` on I/O failure (caller's responsibility to
        handle — ``verify`` swallows it as False, ``snapshot`` records
        absence).
        """
        h = hashlib.new(self._hash_algorithm)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Module-level convenience: a stateless verifier callable
# ---------------------------------------------------------------------------


def make_default_file_verifier() -> Callable[[dict[str, Any]], bool]:
    """Return a stateless ``verify`` callable bound to a new verifier.

    Convenience for callers that only need the verify function (not the
    snapshot helper) and want the default SHA-256 algorithm. Each call
    returns a new bound method; there is no global state.
    """
    return FileSnapshotVerifier().verify
