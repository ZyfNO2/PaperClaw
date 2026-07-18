"""Bridge child-team usage into the parent QueryEngine budget ledger."""

from __future__ import annotations

from typing import Any

from paperclaw.tools.base import ToolContext, ToolResult

_INSTALLED = False


def install_subagent_budget_accounting() -> None:
    """Patch the generic budgeted-tool boundary once.

    The delegate tool receives only the parent's remaining model/tool allowance.
    Its structured child counters are then added to the same parent usage ledger,
    so splitting work cannot bypass QueryEngine limits.
    """

    global _INSTALLED
    if _INSTALLED:
        return

    from paperclaw.harness import agent_runtime_executor as runtime_module

    budgeted_tool = runtime_module._BudgetedTool
    original_execute = budgeted_tool.execute

    def execute(
        self: Any,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        delegated = self.name == "delegate_tasks"
        if delegated:
            context = ToolContext(
                workspace=context.workspace,
                output_limit=context.output_limit,
                stop_token=context.stop_token,
                remaining_model_calls=max(
                    0,
                    self._usage.limits.max_model_calls - self._usage.model_calls,
                ),
                remaining_tool_calls=max(
                    0,
                    self._usage.limits.max_tool_calls - self._usage.tool_calls,
                ),
            )
        result = original_execute(self, arguments, context)
        if delegated:
            child_model_calls = _nonnegative_int(
                result.metadata.get("child_model_calls")
            )
            child_tool_calls = _nonnegative_int(
                result.metadata.get("child_tool_calls")
            )
            self._usage.model_calls += child_model_calls
            self._usage.tool_calls += child_tool_calls
            self._emit(
                "subagent.usage_accounted",
                {
                    "child_model_calls": child_model_calls,
                    "child_tool_calls": child_tool_calls,
                    "parent_model_calls": self._usage.model_calls,
                    "parent_tool_calls": self._usage.tool_calls,
                },
            )
        return result

    budgeted_tool.execute = execute
    _INSTALLED = True


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


__all__ = ["install_subagent_budget_accounting"]
