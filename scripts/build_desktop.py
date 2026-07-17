"""Reproducible PyInstaller onedir build for PaperClaw Desktop."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


def build_desktop(*, clean: bool = True) -> Path:
    try:
        import PyInstaller.__main__
    except ImportError as exc:
        raise RuntimeError(
            "PyInstaller is missing; install PaperClaw with the build extra"
        ) from exc

    root = Path(__file__).resolve().parents[1]
    entry = root / "scripts" / "paperclaw_desktop_entry.py"
    source_root = root / "src"
    static_root = source_root / "paperclaw" / "desktop" / "static"
    dist_root = root / "dist"
    work_root = root / "build" / "pyinstaller"
    spec_root = root / "build" / "spec"

    if clean:
        shutil.rmtree(dist_root / "PaperClaw", ignore_errors=True)
        shutil.rmtree(work_root, ignore_errors=True)
        shutil.rmtree(spec_root, ignore_errors=True)

    args = [
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        "PaperClaw",
        "--paths",
        str(source_root),
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_root),
        "--specpath",
        str(spec_root),
        "--add-data",
        f"{static_root}:paperclaw/desktop/static",
        "--collect-all",
        "webview",
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "hypothesis",
        "--exclude-module",
        "textual",
        str(entry),
    ]
    PyInstaller.__main__.run(args)
    output = dist_root / "PaperClaw"
    if not output.is_dir():
        raise RuntimeError(f"PyInstaller did not create the expected directory: {output}")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args(argv)
    output = build_desktop(clean=not args.no_clean)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
