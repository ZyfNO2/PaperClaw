"""Console entry point for the optional PaperClaw HTTP service."""

from __future__ import annotations

import argparse
from typing import Sequence

from .application import RunApplicationService
from .fastapi_app import create_app
from .runtime_factory import ServiceRuntimeFactory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-active-runs", type=int, default=4)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_active_runs < 1:
        raise SystemExit("--max-active-runs must be positive")
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional install
        raise RuntimeError(
            'Uvicorn is missing; install "paperclaw[service]"'
        ) from exc

    runtime_factory = ServiceRuntimeFactory()
    service = RunApplicationService(
        runtime_factory.create, max_active_runs=args.max_active_runs
    )
    app = create_app(service)
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        service.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
