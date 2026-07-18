"""Console entry point for the optional PaperClaw HTTP service."""

from __future__ import annotations

import argparse
<<<<<<< HEAD
from typing import Sequence

from .application import RunApplicationService
from .fastapi_app import create_app
=======
from pathlib import Path
from typing import Sequence

from paperclaw.durability import SQLiteDurableServiceStore

from .fastapi_app import create_app
from .production_application import DurableRunApplicationService
>>>>>>> 18cf7be
from .runtime_factory import ServiceRuntimeFactory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-active-runs", type=int, default=4)
<<<<<<< HEAD
=======
    parser.add_argument(
        "--database",
        default=str(Path.home() / ".paperclaw" / "service.sqlite3"),
        help="SQLite durable service database path",
    )
>>>>>>> 18cf7be
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

<<<<<<< HEAD
    runtime_factory = ServiceRuntimeFactory()
    service = RunApplicationService(
        runtime_factory.create, max_active_runs=args.max_active_runs
=======
    database_path = Path(args.database).expanduser()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_factory = ServiceRuntimeFactory()
    store = SQLiteDurableServiceStore(database_path)
    service = DurableRunApplicationService(
        runtime_factory.create,
        store,
        max_active_runs=args.max_active_runs,
>>>>>>> 18cf7be
    )
    app = create_app(service)
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        service.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
