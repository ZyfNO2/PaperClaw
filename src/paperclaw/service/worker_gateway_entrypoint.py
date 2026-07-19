"""Standalone authenticated Remote Worker Gateway service entrypoint."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from paperclaw.executor import SubprocessWorkerExecutor, WorkerGatewayService
from paperclaw.executor.http_gateway import create_worker_gateway_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-worker-gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument(
        "--workspace-root",
        action="append",
        dest="workspace_roots",
        required=True,
        help="Allowed worker-host workspace root; repeat for multiple roots",
    )
    parser.add_argument("--max-request-bytes", type=int, default=1_048_576)
    parser.add_argument("--max-result-bytes", type=int, default=4_194_304)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.getenv("PAPERCLAW_WORKER_GATEWAY_TOKEN", "").strip()
    if not token:
        raise SystemExit("PAPERCLAW_WORKER_GATEWAY_TOKEN is required")
    if not 1 <= args.port <= 65_535:
        raise SystemExit("--port must be within [1, 65535]")
    if args.max_request_bytes < 1 or args.max_result_bytes < 1:
        raise SystemExit("gateway payload bounds must be positive")
    roots = [Path(value).expanduser().resolve(strict=True) for value in args.workspace_roots]

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError('Uvicorn is missing; install "paperclaw[service]"') from exc

    gateway = WorkerGatewayService(
        SubprocessWorkerExecutor(),
        allowed_workspace_roots=roots,
        max_request_bytes=args.max_request_bytes,
        max_result_bytes=args.max_result_bytes,
    )
    app = create_worker_gateway_app(
        gateway,
        bearer_token=token,
        max_request_bytes=args.max_request_bytes,
    )
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        gateway.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
