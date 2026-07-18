from __future__ import annotations

from pathlib import Path

path = Path("src/paperclaw/cli.py")
text = path.read_text(encoding="utf-8")
old_import = "from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits\n"
new_import = (
    "from paperclaw.harness import (\n"
    "    ContextOrchestratedAgentRuntimeExecutor,\n"
    "    QueryEngine,\n"
    "    RunLimits,\n"
    ")\n"
    "from paperclaw.memory import build_memory_runtime\n"
)
old_block = '''    executor = AgentRuntimeExecutor(
        OpenAICompatibleModel.from_env(),
        args.workspace,
        enable_verification_gate=args.enable_verification_gate,
        legacy_event_handler=_build_print_event(args.verbose_events),
    )
'''
new_block = '''    components = build_memory_runtime(args.workspace)
    executor = ContextOrchestratedAgentRuntimeExecutor(
        OpenAICompatibleModel.from_env(),
        args.workspace,
        registry=components.tool_registry,
        enable_verification_gate=args.enable_verification_gate,
        legacy_event_handler=_build_print_event(args.verbose_events),
        context_policy=components.context_policy,
        context_source_registry=components.source_registry,
    )
'''
if old_import in text:
    text = text.replace(old_import, new_import, 1)
elif "ContextOrchestratedAgentRuntimeExecutor" not in text:
    raise SystemExit("expected CLI harness import was not found")
if old_block in text:
    text = text.replace(old_block, new_block, 1)
elif "components = build_memory_runtime(args.workspace)" not in text:
    raise SystemExit("expected _run_agent executor block was not found")
path.write_text(text, encoding="utf-8")
