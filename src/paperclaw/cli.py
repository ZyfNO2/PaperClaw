from __future__ import annotations

import argparse
from dataclasses import is_dataclass
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.multiagent.contracts import AgentTask, TeamBudget
from paperclaw.multiagent.coordinator import Coordinator


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip())


def console_print(text: str = "") -> None:
    stream = sys.stdout
    encoding = stream.encoding or "utf-8"
    safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    stream.write(safe + "\n")
    stream.flush()


def json_ready(value):
    """Convert runtime state and dataclasses into JSON-safe output."""
    if hasattr(value, "to_dict"):
        return json_ready(value.to_dict())
    if is_dataclass(value):
        return json_ready(value.__dict__)
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def _build_print_event(verbose: bool):
    def print_event(event: str, payload: dict) -> None:
        if not verbose:
            return
        if event == "reasoning":
            console_print(f"[step {payload['step']}] thinking")
            console_print(payload["reasoning"].strip())
        elif event == "tool_call":
            console_print(f"[step {payload['step']}] tool -> {payload['tool']}")
            console_print(f"reason: {payload['reason']}")
            console_print(json.dumps(payload["arguments"], ensure_ascii=False, indent=2))
        elif event == "tool_result":
            status = "ok" if payload["ok"] else "failed"
            console_print(f"[step {payload['step']}] result <- {payload['tool']} ({status})")
            if payload["error_code"]:
                console_print(f"error: {payload['error_code']}")
            if payload["output"]:
                console_print(payload["output"])
        elif event == "invalid_model_output":
            console_print(f"[step {payload['step']}] invalid model output")
            console_print(payload["error"])
        elif event == "done_proposed":
            console_print(f"[step {payload['step']}] done proposed")
            console_print(f"result: {payload['result']}")
            console_print(f"claimed verification: {payload['verification']}")
        elif event == "done":
            console_print(f"[step {payload['step']}] done")
            console_print(f"result: {payload['result']}")
            console_print(f"verification: {payload['verification_status']}")
        elif event == "verification_planned":
            console_print(f"[step {payload['step']}] verification plan")
            console_print(json.dumps(payload["plan"], ensure_ascii=False, indent=2))
        elif event == "verification_started":
            console_print(f"[step {payload['step']}] verification started")
            console_print(f"claims: {payload['claim_count']}, checks: {payload['check_count']}")
        elif event == "verification_check_completed":
            evidence = payload["evidence"]
            console_print(
                f"[step {payload['step']}] verification check <- "
                f"{evidence['check_id']} ({evidence['status']})"
            )
            console_print(evidence["observed"])
        elif event == "verification_completed":
            console_print(f"[step {payload['step']}] verification result")
            console_print(json.dumps(payload["result"], ensure_ascii=False, indent=2))
        elif event == "reflection_started":
            console_print(f"[step {payload['step']}] reflection started")
            console_print(f"round: {payload['round']}")
        elif event == "reflection_completed":
            console_print(f"[step {payload['step']}] reflection decision")
            console_print(json.dumps(payload["decision"], ensure_ascii=False, indent=2))
        elif event == "stop":
            console_print(f"stopped: {payload['reason']}")
    return print_event


def _run_agent(args: argparse.Namespace) -> int:
    load_dotenv(Path.cwd() / ".env")
    executor = AgentRuntimeExecutor(
        OpenAICompatibleModel.from_env(),
        args.workspace,
        enable_verification_gate=args.enable_verification_gate,
        legacy_event_handler=_build_print_event(args.verbose_events),
    )
    engine = QueryEngine(
        executor,
        conversation_id=f"cli-{uuid4().hex[:12]}",
    )
    result = engine.submit(
        args.task,
        limits=RunLimits(
            max_steps=args.max_steps,
            max_model_calls=args.max_model_calls,
            max_tool_calls=args.max_tool_calls,
        ),
    )

    state = executor.last_state
    if state is None:
        output = {"query_engine": json_ready(result)}
    else:
        output = {
            key: value
            for key, value in state.items()
            if key
            not in {
                "workspace",
                "current_tool_call",
                "event_handler",
                "cancel_event",
            }
        }
        output["history"] = [entry.to_dict() for entry in state["history"]]
        output["query_engine"] = json_ready(result)
    console_print(json.dumps(json_ready(output), ensure_ascii=False, indent=2))
    return 0 if result.status == "completed" else 1


def _run_tui(args: argparse.Namespace) -> int:
    """Launch the optional Textual client without changing the CLI fallback."""

    from paperclaw.tui.runner import run_tui

    fallback = (lambda: _run_agent(args)) if args.task else None
    return run_tui(
        workspace=args.workspace,
        limits=RunLimits(
            max_steps=args.max_steps,
            max_model_calls=args.max_model_calls,
            max_tool_calls=args.max_tool_calls,
        ),
        enable_verification_gate=args.enable_verification_gate,
        initial_task=args.task,
        no_tui=args.no_tui,
        fallback=fallback,
    )


def _run_doctor(args: argparse.Namespace) -> int:
    """Run non-mutating SQLite diagnostics and print one structured report."""

    from paperclaw.context.health import inspect_sqlite_database

    report = inspect_sqlite_database(args.database, full=args.full)
    console_print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def _load_team_plan(plan_path: Path) -> tuple[str, list[AgentTask], TeamBudget]:
    """Load a JSON team plan: {goal, tasks: [...], budget: {...}}."""
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    goal = data["goal"]
    tasks = [AgentTask(**task) for task in data["tasks"]]
    budget = TeamBudget(**data.get("budget", {}))
    return goal, tasks, budget


def _run_team(args: argparse.Namespace) -> int:
    load_dotenv(Path.cwd() / ".env")
    goal, tasks, budget = _load_team_plan(args.plan)
    workspace = Path(args.workspace).resolve(strict=True)

    def team_event_handler(event_type: str, envelope: dict) -> None:
        if not args.verbose_events:
            return
        console_print(
            f"[{event_type}] agent={envelope['agent_id']} "
            f"task={envelope['task_id']} seq={envelope['sequence']}"
        )
        payload = envelope.get("payload")
        if payload:
            console_print(json.dumps(payload, ensure_ascii=False, indent=2))

    coord = Coordinator(
        lambda _agent_id: OpenAICompatibleModel.from_env(),
        workspace,
        budget=budget,
        enable_verification_gate=args.enable_verification_gate,
        event_handler=team_event_handler,
    )
    result = coord.run(goal, tasks)
    console_print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.stop_reason.value in {"completed", "all_tasks_completed"} else 1


def _add_single_agent_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--max-model-calls", type=int, default=10)
    parser.add_argument("--max-tool-calls", type=int, default=20)
    parser.add_argument("--verbose-events", action="store_true")
    parser.add_argument(
        "--enable-verification-gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the v0.02 Verify/Reflection Gate (default: True)",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser so tests can inspect defaults."""
    parser = argparse.ArgumentParser(description="Run the PaperClaw coding agent")
    subparsers = parser.add_subparsers(dest="command")

    agent_parser = subparsers.add_parser("agent", help="Run a single AgentRuntime (default)")
    agent_parser.add_argument("task")
    _add_single_agent_runtime_arguments(agent_parser)

    tui_parser = subparsers.add_parser("tui", help="Run the optional v0.06 Textual client")
    tui_parser.add_argument(
        "task",
        nargs="?",
        help="Optional task to submit on launch; also enables CLI fallback without a TTY",
    )
    _add_single_agent_runtime_arguments(tui_parser)
    tui_parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Skip Textual and use the standard CLI (requires task)",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect an existing PaperClaw SQLite database without modifying it",
    )
    doctor_parser.add_argument("--database", type=Path, required=True)
    doctor_parser.add_argument(
        "--full",
        action="store_true",
        help="Run SQLite integrity_check instead of the faster quick_check",
    )

    team_parser = subparsers.add_parser("team", help="Run a MultiAgent Coordinator team from a JSON plan")
    team_parser.add_argument("--plan", type=Path, required=True)
    team_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    team_parser.add_argument("--verbose-events", action="store_true")
    team_parser.add_argument(
        "--enable-verification-gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the v0.02 Verify/Reflection Gate on every Worker (default: True)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in {"agent", "team", "tui", "doctor", "-h", "--help", "--version", "-v"}:
        argv = ["agent", *argv]

    args = parser.parse_args(argv)
    load_dotenv(Path.cwd() / ".env")

    if args.command == "team":
        return _run_team(args)
    if args.command == "tui":
        return _run_tui(args)
    if args.command == "doctor":
        return _run_doctor(args)
    return _run_agent(args)


if __name__ == "__main__":
    raise SystemExit(main())
