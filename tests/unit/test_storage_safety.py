from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from paperclaw.storage_safety import atomic_write_bytes, resolve_confined_path


def test_resolve_confined_path_rejects_existing_parent_symlink_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    external = tmp_path / "external"
    root.mkdir()
    external.mkdir()
    redirect = root / "redirect"
    try:
        redirect.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this runner")

    with pytest.raises(ValueError, match="escapes"):
        resolve_confined_path(
            root,
            redirect / "data.bin",
            strict=False,
            label="test path",
        )


def test_atomic_write_no_clobber_has_exactly_one_concurrent_winner(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.bin"
    barrier = threading.Barrier(2)

    def write(content: bytes) -> str:
        barrier.wait(timeout=5)
        try:
            atomic_write_bytes(
                target,
                content,
                overwrite=False,
                confinement_root=tmp_path,
            )
            return "created"
        except FileExistsError:
            return "exists"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, (b"alpha" * 1000, b"beta" * 1000)))

    assert sorted(outcomes) == ["created", "exists"]
    assert target.read_bytes() in {b"alpha" * 1000, b"beta" * 1000}
    assert not tuple(tmp_path.glob(".target.bin.*.tmp"))


def test_atomic_overwrite_replaces_complete_content_and_cleans_temp(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"old")

    atomic_write_bytes(
        target,
        b"new-complete-value",
        overwrite=True,
        confinement_root=tmp_path,
    )

    assert target.read_bytes() == b"new-complete-value"
    assert not tuple(tmp_path.glob(".target.bin.*.tmp"))
