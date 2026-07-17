"""Installed console entry point with an optional desktop command shim."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    resolved = list(sys.argv[1:] if argv is None else argv)
    if resolved and resolved[0] == "gui":
        from paperclaw.desktop.app import main as desktop_main

        return desktop_main(resolved[1:])

    from paperclaw.cli import main as legacy_main

    return legacy_main(resolved)


if __name__ == "__main__":
    raise SystemExit(main())
