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
    engine = QueryEngine(executor, conversation_id=f"cli-{uuid4().hex[:12]}")
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
        database=args.database,
        fallback=fallback,
    )


def _run_doctor(args: argparse.Namespace) -> int:
    from paperclaw.context.health import inspect_sqlite_database

    report = inspect_sqlite_database(args.database, full=args.full)
    output = report.to_dict()
    output["full"] = bool(args.full)
    console_print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def _trace_reader(database: Path):
    from paperclaw.trace import SQLiteTraceReader, TraceRedactor

    api_key = os.environ.get("PAPERCLAW_API_KEY", "")
    return SQLiteTraceReader(
        database,
        redactor=TraceRedactor(secret_values=[api_key]),
    )


def _print_error(exc: Exception) -> int:
    console_print(
        json.dumps(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1


def _run_trace_export(args: argparse.Namespace) -> int:
    from paperclaw.trace import TraceReadError, export_trace_jsonl

    try:
        summary = export_trace_jsonl(
            _trace_reader(args.database),
            args.run_id,
            args.output,
            require_terminal=not args.allow_partial,
        )
    except (TraceReadError, OSError, ValueError) as exc:
        return _print_error(exc)
    output = summary.to_dict()
    output["ok"] = True
    output["partial_allowed"] = bool(args.allow_partial)
    console_print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _run_trace_inspect(args: argparse.Namespace) -> int:
    from paperclaw.trace import TraceReadError, inspect_run_trace, render_inspection_text

    try:
        inspection = inspect_run_trace(
            _trace_reader(args.database),
            args.run_id,
            require_terminal=not args.allow_partial,
            max_events=args.max_events,
        )
    except (TraceReadError, OSError, ValueError) as exc:
        return _print_error(exc)
    if args.format == "json":
        output = inspection.to_dict()
        output["ok"] = True
        output["partial_allowed"] = bool(args.allow_partial)
        console_print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        console_print(render_inspection_text(inspection))
    return 0


def _run_trace_replay(args: argparse.Namespace) -> int:
    from paperclaw.replay import (
        RecordedReplayError,
        render_recorded_replay_text,
        replay_recorded_trace,
    )
    from paperclaw.trace import TraceReadError

    try:
        result = replay_recorded_trace(
            _trace_reader(args.database),
            args.run_id,
            require_terminal=not args.allow_partial,
            strict=args.strict,
            max_frames=args.max_frames,
        )
    except (RecordedReplayError, TraceReadError, OSError, ValueError) as exc:
        return _print_error(exc)
    if args.format == "json":
        output = result.to_dict()
        output["ok"] = result.faithful
        output["partial_allowed"] = bool(args.allow_partial)
        console_print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        console_print(render_recorded_replay_text(result))
    return 0 if result.faithful else 1


def _run_trace_eval(args: argparse.Namespace) -> int:
    from paperclaw.eval import EvalThresholds, evaluate_trace, render_trace_eval_text
    from paperclaw.trace import TraceReadError

    try:
        report = evaluate_trace(
            _trace_reader(args.database),
            args.run_id,
            thresholds=EvalThresholds(
                require_completed=args.require_completed,
                require_replay_faithful=args.require_replay_faithful,
                max_tool_failure_rate=args.max_tool_failure_rate,
                max_retries=args.max_retries,
                max_errors=args.max_errors,
                max_wall_duration_ms=args.max_wall_duration_ms,
                max_reflection_rounds=args.max_reflection_rounds,
            ),
            require_terminal=not args.allow_partial,
        )
    except (TraceReadError, OSError, ValueError) as exc:
        return _print_error(exc)
    if args.format == "json":
        output = report.to_dict()
        output["ok"] = report.overall_passed
        output["partial_allowed"] = bool(args.allow_partial)
        console_print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        console_print(render_trace_eval_text(report))
    return 0 if report.overall_passed else 1


def _run_trace_push(args: argparse.Namespace) -> int:
    from paperclaw.exporters import (
        ExternalExportError,
        ExternalExportPolicy,
        HttpTraceExporter,
    )
    from paperclaw.trace import TraceReadError

    token = os.environ.get(args.auth_token_env, "") if args.auth_token_env else ""
    try:
        exporter = HttpTraceExporter(
            args.endpoint,
            policy=ExternalExportPolicy(
                enabled=args.enable_external_export,
                allowed_hosts=tuple(args.allow_host or ()),
                timeout_seconds=args.timeout_seconds,
                max_events=args.max_events,
                max_payload_bytes=args.max_payload_bytes,
            ),
            bearer_token=token,
        )
        summary = exporter.export_run(
            _trace_reader(args.database),
            args.run_id,
            require_terminal=not args.allow_partial,
        )
    except (ExternalExportError, TraceReadError, OSError, ValueError) as exc:
        return _print_error(exc)
    output = summary.to_dict()
    output["ok"] = True
    output["partial_allowed"] = bool(args.allow_partial)
    console_print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _read_live_replay_task(args: argparse.Namespace) -> str:
    if args.task is not None:
        return args.task
    return args.task_file.read_text(encoding="utf-8")


def _run_trace_live_replay(args: argparse.Namespace) -> int:
    from paperclaw.agent.flow import default_registry
    from paperclaw.context.repository import SQLiteRepository
    from paperclaw.replay import (
        LIVE_REPLAY_CONFIRMATION,
        LiveReplayAgentRuntimeExecutor,
        LiveReplayError,
        LiveReplayPolicy,
        execute_live_replay,
        prepare_live_replay,
    )
    from paperclaw.tools.registry import ToolRegistry
    from paperclaw.trace import TraceReadError

    source_database = args.database.expanduser().resolve()
    target_database = args.output_database.expanduser().resolve()
    try:
        if source_database == target_database:
            raise LiveReplayError(
                "source and target databases must be different files"
            )
        if not target_database.parent.is_dir():
            raise LiveReplayError(
                f"target database parent does not exist: {target_database.parent}"
            )
        if target_database.exists() and not target_database.is_file():
            raise LiveReplayError(
                f"target database is not a file: {target_database}"
            )
        task = _read_live_replay_task(args)
        policy = LiveReplayPolicy(
            enabled=args.enable_live_replay,
            confirmation=args.confirm,
            require_source_completed=not args.allow_source_noncompleted,
            require_recorded_faithful=True,
            allowed_tools=tuple(args.allow_tool or ()),
            allow_mutating_tools=args.allow_mutating_tools,
            limits=RunLimits(
                max_steps=args.max_steps,
                max_model_calls=args.max_model_calls,
                max_tool_calls=args.max_tool_calls,
            ),
        )
        if args.confirm != LIVE_REPLAY_CONFIRMATION:
            raise LiveReplayError(
                "confirmation must equal LIVE_REPLAY_EXECUTES_EXTERNAL_ACTIONS"
            )
        plan = prepare_live_replay(
            _trace_reader(source_database),
            args.run_id,
            task,
            policy=policy,
        )
        catalog = default_registry()
        unknown = [name for name in plan.allowed_tools if name not in catalog.names]
        if unknown:
            raise LiveReplayError(
                "unknown live replay tools: " + ", ".join(sorted(unknown))
            )
        registry = ToolRegistry(catalog.get(name) for name in plan.allowed_tools)
        repository = SQLiteRepository(target_database, migrate=True)
        try:
            executor = LiveReplayAgentRuntimeExecutor(
                OpenAICompatibleModel.from_env(),
                args.workspace,
                plan=plan,
                registry=registry,
                repository=repository,
                enable_verification_gate=args.enable_verification_gate,
            )
            result = execute_live_replay(plan, executor)
        finally:
            repository.close()
    except (
        KeyError,
        LiveReplayError,
        OSError,
        RuntimeError,
        TraceReadError,
        ValueError,
    ) as exc:
        return _print_error(exc)

    output = result.to_dict()
    output["ok"] = result.run_result.status == "completed"
    output["source_database"] = str(source_database)
    output["target_database"] = str(target_database)
    console_print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if result.run_result.status == "completed" else 1


def _load_team_plan(plan_path: Path) -> tuple[str, list[AgentTask], TeamBudget]:
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    return (
        data["goal"],
        [AgentTask(**task) for task in data["tasks"]],
        TeamBudget(**data.get("budget", {})),
    )


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
    )


def _add_trace_read_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--allow-partial", action="store_true")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the PaperClaw coding agent")
    subparsers = parser.add_subparsers(dest="command")

    agent_parser = subparsers.add_parser("agent")
    agent_parser.add_argument("task")
    _add_single_agent_runtime_arguments(agent_parser)

    tui_parser = subparsers.add_parser("tui")
    tui_parser.add_argument("task", nargs="?")
    _add_single_agent_runtime_arguments(tui_parser)
    tui_parser.add_argument("--no-tui", action="store_true")
    tui_parser.add_argument("--database", type=Path)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--database", type=Path, required=True)
    doctor_parser.add_argument("--full", action="store_true")

    trace_parser = subparsers.add_parser("trace")
    trace_subparsers = trace_parser.add_subparsers(dest="trace_command", required=True)

    trace_export_parser = trace_subparsers.add_parser("export")
    trace_export_parser.add_argument("--database", type=Path, required=True)
    trace_export_parser.add_argument("--run-id", required=True)
    trace_export_parser.add_argument("--output", type=Path, required=True)
    trace_export_parser.add_argument("--allow-partial", action="store_true")

    trace_inspect_parser = trace_subparsers.add_parser("inspect")
    _add_trace_read_arguments(trace_inspect_parser)
    trace_inspect_parser.add_argument("--max-events", type=int)

    trace_replay_parser = trace_subparsers.add_parser("replay")
    _add_trace_read_arguments(trace_replay_parser)
    trace_replay_parser.add_argument("--max-frames", type=int)
    trace_replay_parser.add_argument("--strict", action="store_true")

    trace_eval_parser = trace_subparsers.add_parser("eval")
    _add_trace_read_arguments(trace_eval_parser)
    trace_eval_parser.add_argument("--require-completed", action="store_true")
    trace_eval_parser.add_argument(
        "--require-replay-faithful",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    trace_eval_parser.add_argument("--max-tool-failure-rate", type=float)
    trace_eval_parser.add_argument("--max-retries", type=int)
    trace_eval_parser.add_argument("--max-errors", type=int)
    trace_eval_parser.add_argument("--max-wall-duration-ms", type=int)
    trace_eval_parser.add_argument("--max-reflection-rounds", type=int)

    trace_push_parser = trace_subparsers.add_parser("push")
    trace_push_parser.add_argument("--database", type=Path, required=True)
    trace_push_parser.add_argument("--run-id", required=True)
    trace_push_parser.add_argument("--endpoint", required=True)
    trace_push_parser.add_argument("--allow-host", action="append", required=True)
    trace_push_parser.add_argument("--enable-external-export", action="store_true")
    trace_push_parser.add_argument(
        "--auth-token-env",
        default="PAPERCLAW_EXPORT_TOKEN",
    )
    trace_push_parser.add_argument("--timeout-seconds", type=float, default=10)
    trace_push_parser.add_argument("--max-events", type=int, default=10_000)
    trace_push_parser.add_argument(
        "--max-payload-bytes",
        type=int,
        default=5_000_000,
    )
    trace_push_parser.add_argument("--allow-partial", action="store_true")

    live_replay_parser = trace_subparsers.add_parser("live-replay")
    live_replay_parser.add_argument("--database", type=Path, required=True)
    live_replay_parser.add_argument("--run-id", required=True)
    live_replay_parser.add_argument("--output-database", type=Path, required=True)
    live_replay_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    task_group = live_replay_parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task")
    task_group.add_argument("--task-file", type=Path)
    live_replay_parser.add_argument("--enable-live-replay", action="store_true")
    live_replay_parser.add_argument("--confirm", required=True)
    live_replay_parser.add_argument("--allow-tool", action="append", default=[])
    live_replay_parser.add_argument("--allow-mutating-tools", action="store_true")
    live_replay_parser.add_argument(
        "--allow-source-noncompleted",
        action="store_true",
    )
    live_replay_parser.add_argument("--max-steps", type=int, default=8)
    live_replay_parser.add_argument("--max-model-calls", type=int, default=6)
    live_replay_parser.add_argument("--max-tool-calls", type=int, default=6)
    live_replay_parser.add_argument(
        "--enable-verification-gate",
        action=argparse.BooleanOptionalAction,
        default=False,
    )

    team_parser = subparsers.add_parser("team")
    team_parser.add_argument("--plan", type=Path, required=True)
    team_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    team_parser.add_argument("--verbose-events", action="store_true")
    team_parser.add_argument(
        "--enable-verification-gate",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in {
        "agent",
        "team",
        "tui",
        "doctor",
        "trace",
        "-h",
        "--help",
        "--version",
        "-v",
    }:
        argv = ["agent", *argv]

    args = parser.parse_args(argv)
    load_dotenv(Path.cwd() / ".env")

    if args.command == "team":
        return _run_team(args)
    if args.command == "tui":
        return _run_tui(args)
    if args.command == "doctor":
        return _run_doctor(args)
    if args.command == "trace":
        handlers = {
            "export": _run_trace_export,
            "inspect": _run_trace_inspect,
            "replay": _run_trace_replay,
            "eval": _run_trace_eval,
            "push": _run_trace_push,
            "live-replay": _run_trace_live_replay,
        }
        return handlers[args.trace_command](args)
    return _run_agent(args)


if __name__ == "__main__":
    raise SystemExit(main())
