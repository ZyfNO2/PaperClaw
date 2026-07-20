"""CLI for one durable bus-driven MultiAgent run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from paperclaw.cli import load_dotenv
from paperclaw.eval.aggregate import MeteredChatModel, PricingTable, UsageCollector
from paperclaw.message_bus import SQLiteMessageBusStore
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.multiagent.bus_runtime import (
    BusDrivenTeamRuntime,
    SQLiteChoreographyStateStore,
    TeamRunRequest,
)
from paperclaw.multiagent.coordinator import Coordinator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-team-run")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--database", type=Path, default=Path(".paperclaw/team-bus.sqlite3"))
    parser.add_argument(
        "--state-database",
        type=Path,
        default=Path(".paperclaw/team-choreography.sqlite3"),
    )
    parser.add_argument("--pricing", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--consumer-id", default="multiagent-runtime")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--disable-verification-gate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = args.workspace.expanduser().resolve(strict=True)
    load_dotenv(workspace / ".env")
    pricing = _load_pricing(args.pricing)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise SystemExit("plan must contain one JSON object")
    plan.setdefault("schema_version", "v1")
    plan.setdefault("request_id", f"team-{uuid4().hex[:16]}")
    request = TeamRunRequest.from_payload(plan)

    database = _resolve_under_workspace(workspace, args.database)
    state_database = _resolve_under_workspace(workspace, args.state_database)
    bus = SQLiteMessageBusStore(database)
    state = SQLiteChoreographyStateStore(state_database)

    def coordinator_factory(budget, event_handler, usage):
        def model_factory(_agent_id: str):
            return MeteredChatModel(
                OpenAICompatibleModel.from_env(),
                usage,
                provider=os.environ.get("PAPERCLAW_PROVIDER"),
                model=os.environ.get("PAPERCLAW_MODEL"),
            )

        return Coordinator(
            model_factory,
            workspace,
            budget=budget,
            enable_verification_gate=not args.disable_verification_gate,
            event_handler=event_handler,
        )

    runtime = BusDrivenTeamRuntime(
        bus,
        state,
        coordinator_factory,
        consumer_id=args.consumer_id,
        max_attempts=args.max_attempts,
        usage_factory=lambda: UsageCollector(pricing),
    )
    outcome = runtime.execute(request)
    encoded = json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = _resolve_under_workspace(workspace, args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    if outcome.dead_lettered:
        return 2
    if outcome.result is None:
        return 1
    stop_reason = getattr(outcome.result.stop_reason, "value", outcome.result.stop_reason)
    return 0 if str(stop_reason) in {"completed", "all_tasks_completed"} else 1


def _load_pricing(path: Path | None) -> PricingTable:
    if path is None:
        return PricingTable()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("pricing file must contain a JSON object")
    return PricingTable.from_mapping(payload)


def _resolve_under_workspace(workspace: Path, path: Path) -> Path:
    candidate = path.expanduser()
    resolved = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("path must remain inside workspace") from exc
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
