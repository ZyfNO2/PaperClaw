"""Installed console entry point with optional product, desktop and service shims."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    resolved = list(sys.argv[1:] if argv is None else argv)
    if resolved and resolved[0] in {"artifact", "capabilities", "project"}:
        from paperclaw.product_cli import main as product_main

        return product_main(resolved)
    if resolved and resolved[0] == "gui":
        from paperclaw.desktop.bootstrap import main as desktop_main

        return desktop_main(resolved[1:])
    if resolved and resolved[0] == "api":
        from paperclaw.service.entrypoint import main as service_main

        return service_main(resolved[1:])
    if resolved and resolved[0] == "research-eval":
        from paperclaw.research_eval.cli import main as research_eval_main

        return research_eval_main(resolved[1:])

    import paperclaw.cli
    from paperclaw.lsp.bootstrap import install_cli_lsp_extension
    from paperclaw.multiagent.bootstrap import install_cli_subagent_extension
    from paperclaw.planning.bootstrap import install_cli_plan_skill_extension
    from paperclaw.tasks.bootstrap import (
        install_cli_task_extension,
        shutdown_task_runtimes,
    )

    install_cli_subagent_extension(paperclaw.cli)
    install_cli_task_extension(paperclaw.cli)
    install_cli_plan_skill_extension(paperclaw.cli)
    install_cli_lsp_extension(paperclaw.cli)
    try:
        return paperclaw.cli.main(resolved)
    finally:
        # A CLI invocation owns its process-scoped supervisors. Stop them while
        # Python and asyncio executors are still fully available instead of
        # relying only on interpreter-finalization ordering.
        shutdown_task_runtimes()


if __name__ == "__main__":
    raise SystemExit(main())
