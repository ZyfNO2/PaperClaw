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

    app = PaperClawApp(
        engine_factory=_build_engine_factory(
            workspace=workspace,
            enable_verification_gate=enable_verification_gate,
        ),
        limits=limits,
        initial_task=initial_task,
    )
    result = app.run()
    return int(result or 0)


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


def _build_engine_factory(*, workspace: Path, enable_verification_gate: bool):
    """Build one fresh conversation-scoped engine for each `/new` command."""

    resolved_workspace = Path(workspace).resolve(strict=True)

    def create_engine(event_handler):
        from .bridge import TUIEventBridge

        bridge = TUIEventBridge(event_handler)
        # Imports remain below the fallback gate so missing Textual never changes
        # the existing CLI import path or its dependency surface.
        from paperclaw.harness import AgentRuntimeExecutor, QueryEngine
        from paperclaw.models.adapters import OpenAICompatibleModel

        executor = AgentRuntimeExecutor(
            OpenAICompatibleModel.from_env(),
            resolved_workspace,
            enable_verification_gate=enable_verification_gate,
            legacy_event_handler=bridge.handle_legacy_event,
        )
        return QueryEngine(
            executor,
            conversation_id=f"tui-{uuid4().hex[:12]}",
            event_handler=bridge.handle_query_event,
        )

    return create_engine
