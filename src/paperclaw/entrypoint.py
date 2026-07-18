<<<<<<< HEAD
<<<<<<< HEAD
"""Installed console entry point with optional client and service shims."""
=======
"""Installed console entry point with optional desktop and service shims."""
>>>>>>> 18cf7be
=======
"""Installed console entry point with optional desktop and service shims."""
>>>>>>> 70e7334

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    resolved = list(sys.argv[1:] if argv is None else argv)
    if resolved and resolved[0] == "gui":
        from paperclaw.desktop.bootstrap import main as desktop_main

        return desktop_main(resolved[1:])
    if resolved and resolved[0] == "api":
        from paperclaw.service.entrypoint import main as service_main

        return service_main(resolved[1:])
    if resolved and resolved[0] == "research-eval":
        from paperclaw.research_eval.cli import main as research_eval_main

        return research_eval_main(resolved[1:])

    from paperclaw.cli import main as legacy_main

    return legacy_main(resolved)


if __name__ == "__main__":
    raise SystemExit(main())
