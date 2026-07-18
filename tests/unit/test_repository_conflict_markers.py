from __future__ import annotations

from pathlib import Path


_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")
_TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".js",
    ".css",
    ".html",
}


def test_repository_has_no_unresolved_merge_conflict_markers() -> None:
    root = Path(__file__).resolve().parents[2]
    candidates = [root / "pyproject.toml"]
    for directory in (root / "src", root / "tests", root / ".github"):
        candidates.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES
        )

    failures: list[str] = []
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(line.startswith(marker) for marker in _MARKERS):
                failures.append(f"{path.relative_to(root)}:{line_number}: {line}")

    assert failures == [], "unresolved merge conflict markers:\n" + "\n".join(failures)
