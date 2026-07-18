"""Optional runtime installation helpers for dynamic subagent delegation."""

from __future__ import annotations

from typing import Any

from .tool import SubagentTaskTool

_CLI_MARKER = "_paperclaw_subagent_cli_extension"


def install_cli_subagent_extension(cli_module: Any) -> None:
    """Wrap the CLI memory-runtime builder without rewriting the legacy parser."""

    if getattr(cli_module, _CLI_MARKER, False):
        return
    original_build_memory_runtime = cli_module.build_memory_runtime

    def build_memory_runtime_with_subagents(*args: Any, **kwargs: Any):
        components = original_build_memory_runtime(*args, **kwargs)
        if "delegate_tasks" not in components.tool_registry.names:
            components.tool_registry.register(
                SubagentTaskTool(
                    lambda _agent_id: cli_module.OpenAICompatibleModel.from_env(),
                    enable_verification_gate=True,
                )
            )
        return components

    cli_module.build_memory_runtime = build_memory_runtime_with_subagents
    setattr(cli_module, _CLI_MARKER, True)


__all__ = ["install_cli_subagent_extension"]
