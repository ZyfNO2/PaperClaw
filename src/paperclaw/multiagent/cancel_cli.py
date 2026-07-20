"""Submit an idempotent cancellation request for an active Team Run."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

from paperclaw.message_bus import MessageDraft, SQLiteMessageBusStore
from paperclaw.multiagent.resilient_runtime import (
    TEAM_CANCEL_TOPIC,
    TeamCancellationRequest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-team-cancel")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--database", type=Path, default=Path(".paperclaw/team-bus.sqlite3"))
    parser.add_argument("--consumer-id", default="multiagent-runtime")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--cancellation-id")
    parser.add_argument("--reason", default="operator requested cancellation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = args.workspace.expanduser().resolve(strict=True)
    database = _resolve_under_workspace(workspace, args.database)
    cancellation = TeamCancellationRequest(
        cancellation_id=args.cancellation_id or f"cancel-{uuid4().hex[:16]}",
        request_id=args.request_id,
        task_ids=tuple(args.task_id),
        reason=args.reason,
    )
    recipient_id = _cancellation_recipient(args.consumer_id, cancellation.request_id)
    message = SQLiteMessageBusStore(database).publish(
        MessageDraft(
            topic=TEAM_CANCEL_TOPIC,
            sender_id="team-cancel-cli",
            recipient_id=recipient_id,
            idempotency_key=cancellation.cancellation_id,
            payload=cancellation.to_payload(),
            headers={"schema_version": "v1", "message_type": "team.cancel.requested"},
        )
    ).message
    sys.stdout.write(
        json.dumps(
            {
                "cancellation_id": cancellation.cancellation_id,
                "request_id": cancellation.request_id,
                "task_ids": list(cancellation.task_ids),
                "message_id": message.message_id,
                "recipient_id": recipient_id,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return 0


def _cancellation_recipient(consumer_id: str, request_id: str) -> str:
    digest = sha256(request_id.encode("utf-8")).hexdigest()[:16]
    return f"{consumer_id}.cancel.{digest}"


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
