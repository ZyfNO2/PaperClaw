"""Standalone runner for the MultiAgent Textual dashboard.

Use ``python -m paperclaw.tui.team_runner --plan team-plan.json``. Keeping this
entry point separate avoids changing the active v0.07.x CLI stack while still
providing a real executable UI boundary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TextIO

from paperclaw.multiagent.contracts import AgentTask, TeamBudget


class TeamPlanError(ValueError):
    """Raised when a team plan cannot be converted into runtime contracts."""


def load_team_plan(plan_path: Path) -> tuple[str, list[AgentTask], TeamBudget]:
    """Load and minimally validate ``{goal, tasks, budget}`` JSON."""

    data = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TeamPlanError("team plan root must be a JSON object")
    goal = data.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise TeamPlanError("team plan goal must be a non-empty string")
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list):
        raise TeamPlanError("team plan tasks must be a JSON array")
    try:
        tasks = [AgentTask(**item) for item in raw_tasks if isinstance(item, dict)]
    except (TypeError, ValueError) as exc:
        raise TeamPlanError(f"invalid task contract: {exc}") from exc
    if len(tasks) != len(raw_tasks):
        raise TeamPlanError("every team task must be a JSON object")
    raw_budget = data.get("budget", {})
    if not isinstance(raw_budget, dict):
        raise TeamPlanError("team plan budget must be a JSON object")
    try:
        budget = TeamBudget(**raw_budget)
    except (TypeError, ValueError) as exc:
        raise TeamPlanError(f"invalid team budget: {exc}") from exc
    return goal.strip(), tasks, budget


def run_team_tui(
    *,
    plan_path: Path,
    workspace: Path,
    enable_verification_gate: bool = True,
    no_tui: bool = False,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Launch the team dashboard after optional-dependency and TTY checks."""

    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    reason = _unavailable_reason(no_tui=no_tui, stdin=stdin, stdout=stdout)
    if reason is not None:
        print(f"PaperClaw MultiAgent TUI unavailable: {reason}", file=stderr)
        print('Install with `pip install -e ".[tui]"` and run in a real TTY.', file=stderr)
        return 2

    goal, tasks, budget = load_team_plan(plan_path)
    resolved_workspace = workspace.expanduser().resolve(strict=True)

    from paperclaw.models.adapters import OpenAICompatibleModel
    from paperclaw.multiagent.coordinator import Coordinator

    from .team_app import TeamApp

    def coordinator_factory(event_handler):
        return Coordinator(
            lambda _agent_id: OpenAICompatibleModel.from_env(),
            resolved_workspace,
            budget=budget,
            enable_verification_gate=enable_verification_gate,
            event_handler=event_handler,
        )

    app = TeamApp(
        coordinator_factory=coordinator_factory,
        goal=goal,
        tasks=tasks,
    )
    result = app.run()
    return int(result or 0)


def _unavailable_reason(*, no_tui: bool, stdin: TextIO, stdout: TextIO) -> str | None:
    if no_tui:
        return "disabled by --no-tui"
    from .runner import textual_available

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the PaperClaw MultiAgent dashboard")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--no-tui", action="store_true")
    parser.add_argument(
        "--enable-verification-gate",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return run_team_tui(
            plan_path=args.plan,
            workspace=args.workspace,
            enable_verification_gate=args.enable_verification_gate,
            no_tui=args.no_tui,
        )
    except (OSError, json.JSONDecodeError, TeamPlanError) as exc:
        print(f"Invalid team plan or workspace: {type(exc).__name__}: {str(exc)[:500]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
