from __future__ import annotations

from pathlib import Path

from .base import ToolValidationError


def resolve_workspace_path(workspace: Path, raw_path: str, *, must_exist: bool = False) -> Path:
    root = workspace.resolve(strict=True)
    candidate = Path(raw_path)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolValidationError(f"path escapes workspace: {raw_path}") from exc
    if must_exist and not resolved.exists():
        raise ToolValidationError(f"path does not exist: {raw_path}")
    return resolved
