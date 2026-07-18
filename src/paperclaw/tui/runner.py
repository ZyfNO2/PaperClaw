"""Optional-dependency and terminal fallback boundary for the TUI."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import sys
from typing import Callable, TextIO
from uuid import uuid4

from paperclaw.harness import RunLimits

Fallback = Callable[[], int]


def textual_available() -> bool:
    """Return whether the optional Textual dependency can be imported."""

    try:
        return find_spec("textual") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def run_tui(
    *,
    workspace: Path,
    limits: RunLimits,
    enable_verification_gate: bool,
    initial_task: str | None,
    no_tui: bool,
    database: Path | None = None,
    fallback: Fallback | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Launch Textual or fall back to one-shot CLI execution when possible."""

    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    reason = _unavailable_reason(no_tui=no_tui, stdin=stdin, stdout=stdout)
    if reason is not None:
        print(f"PaperClaw TUI unavailable: {reason}", file=stderr)
        if initial_task and fallback is not None:
            print("Falling back to the standard single-agent CLI.", file=stderr)
            return fallback()
        print(
            "Provide a task for CLI fallback, or run `paperclaw agent <task>`. "
            "Install the UI with `pip install -e \".[tui]\"`.",
            file=stderr,
        )
        return 2

    from .app import PaperClawApp

    session_runtime = None
    try:
        if database is not None:
            from paperclaw.session_commands import open_persistent_session_runtime

            session_runtime = open_persistent_session_runtime(database)

        app = PaperClawApp(
            engine_factory=_build_engine_factory(
                workspace=workspace,
                enable_verification_gate=enable_verification_gate,
                session_runtime=session_runtime,
            ),
            limits=limits,
            initial_task=initial_task,
            session_commands=(
                session_runtime.commands if session_runtime is not None else None
            ),
        )
        result = app.run()
        return int(result or 0)
    finally:
        if session_runtime is not None:
            session_runtime.close()


def _unavailable_reason(*, no_tui: bool, stdin: TextIO, stdout: TextIO) -> str | None:
    if no_tui:
        return "disabled by --no-tui"
    if not textual_available():
        return "optional dependency `textual` is not installed"
    if not _is_tty(stdin) or not _is_tty(stdout):
        return "stdin and stdout must both be attached to a TTY"
    return None


def _is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


def _build_engine_factory(
    *,
    workspace: Path,
    enable_verification_gate: bool,
    session_runtime=None,
):
    """Build one conversation-scoped engine for `/new` or safe reopen."""

    resolved_workspace = Path(workspace).resolve(strict=True)

    def create_engine(event_handler, conversation_id: str | None = None):
        from .bridge import TUIEventBridge

        bridge = TUIEventBridge(event_handler)
        # Imports remain below the fallback gate so missing Textual never changes
        # the existing CLI import path or its dependency surface.
        from paperclaw.harness import (
            ContextOrchestratedAgentRuntimeExecutor,
            QueryEngine,
        )
        from paperclaw.memory import build_memory_runtime
        from paperclaw.models.adapters import OpenAICompatibleModel
        from paperclaw.multiagent.tool import SubagentTaskTool

        model = OpenAICompatibleModel.from_env()
        if session_runtime is None:
            components = build_memory_runtime(resolved_workspace)
            components.tool_registry.register(
                SubagentTaskTool(
                    lambda _agent_id: OpenAICompatibleModel.from_env(),
                    enable_verification_gate=enable_verification_gate,
                )
            )
            executor = ContextOrchestratedAgentRuntimeExecutor(
                model,
                resolved_workspace,
                registry=components.tool_registry,
                enable_verification_gate=enable_verification_gate,
                legacy_event_handler=bridge.handle_legacy_event,
                context_policy=components.context_policy,
                context_source_registry=components.source_registry,
            )
        else:
            executor = session_runtime.create_executor(
                model,
                resolved_workspace,
                enable_verification_gate=enable_verification_gate,
                legacy_event_handler=bridge.handle_legacy_event,
            )
        return QueryEngine(
            executor,
            conversation_id=conversation_id or f"tui-{uuid4().hex[:12]}",
            event_handler=bridge.handle_query_event,
        )

    return create_engine
