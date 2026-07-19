"""Cross-platform confined and race-safe local filesystem primitives."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def resolve_confined_path(
    root: str | Path,
    candidate: str | Path,
    *,
    strict: bool,
    label: str,
) -> Path:
    """Resolve ``candidate`` and require it to stay below ``root``.

    ``Path.resolve(strict=False)`` still resolves every existing parent symlink,
    which is what prevents a workspace-local parent such as ``.paperclaw`` from
    redirecting persistence outside the selected workspace.
    """

    resolved_root = Path(root).expanduser().resolve(strict=True)
    resolved_candidate = Path(candidate).expanduser().resolve(strict=strict)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its configured root") from exc
    return resolved_candidate


def atomic_write_bytes(
    target: str | Path,
    content: bytes,
    *,
    overwrite: bool,
    confinement_root: str | Path | None = None,
) -> Path:
    """Install bytes using an exclusive random temporary file.

    ``overwrite=False`` uses an atomic hard-link no-clobber operation when the
    filesystem supports it. The fallback still uses ``O_EXCL`` so a concurrent
    writer can never replace an existing destination.
    """

    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    if confinement_root is not None:
        resolve_confined_path(
            confinement_root,
            path.parent,
            strict=True,
            label="write parent",
        )

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if confinement_root is not None:
            resolve_confined_path(
                confinement_root,
                path.parent,
                strict=True,
                label="write parent",
            )
        if overwrite:
            os.replace(temporary, path)
        else:
            _install_no_clobber(temporary, path, content)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _install_no_clobber(temporary: Path, target: Path, content: bytes) -> None:
    try:
        os.link(temporary, target)
        return
    except FileExistsError:
        raise FileExistsError(f"target already exists: {target}") from None
    except OSError:
        # Some filesystems do not support hard links. O_EXCL preserves the
        # no-clobber contract even though the fallback cannot expose the fully
        # written file in one rename operation.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor: int | None = None
        try:
            descriptor = os.open(target, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            raise FileExistsError(f"target already exists: {target}") from None
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            target.unlink(missing_ok=True)
            raise


__all__ = ["atomic_write_bytes", "resolve_confined_path"]
