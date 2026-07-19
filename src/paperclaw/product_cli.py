"""Product-foundation CLI commands kept separate from the legacy runtime parser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from paperclaw.capabilities import default_capability_catalog
from paperclaw.projects import (
    ProjectManifestStore,
    build_project_index,
    inspect_project_index,
)


def _print(value: str) -> None:
    stream = sys.stdout
    encoding = stream.encoding or "utf-8"
    safe = value.encode(encoding, errors="replace").decode(
        encoding, errors="replace"
    )
    stream.write(safe + "\n")
    stream.flush()


def _json(value: object) -> None:
    _print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PaperClaw product foundations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capabilities = subparsers.add_parser("capabilities")
    capabilities.add_argument(
        "--format", choices=("text", "json"), default="text"
    )
    capabilities.add_argument(
        "--status",
        choices=("shipped", "foundation", "experimental", "planned"),
    )
    capabilities.add_argument(
        "--surface",
        choices=("library", "cli", "tui", "desktop", "service"),
    )

    project = subparsers.add_parser("project")
    project.add_argument("--workspace", type=Path, default=Path.cwd())
    project_subparsers = project.add_subparsers(
        dest="project_command", required=True
    )

    project_init = project_subparsers.add_parser("init")
    project_init.add_argument("--name", required=True)
    project_init.add_argument("--force", action="store_true")

    project_subparsers.add_parser("show")
    project_subparsers.add_parser("validate")

    project_index = project_subparsers.add_parser("index")
    project_index.add_argument("--max-file-bytes", type=int, default=5_000_000)
    return parser


def _run_capabilities(args: argparse.Namespace) -> int:
    catalog = default_capability_catalog()
    if args.format == "json":
        _print(catalog.to_json(maturity=args.status, surface=args.surface))
    else:
        _print(catalog.render_text(maturity=args.status, surface=args.surface))
    return 0


def _project_store(args: argparse.Namespace) -> ProjectManifestStore:
    return ProjectManifestStore(args.workspace)


def _run_project(args: argparse.Namespace) -> int:
    store = _project_store(args)
    if args.project_command == "init":
        manifest = store.initialize(args.name, force=args.force)
        _json(
            {
                "ok": True,
                "manifest_path": str(store.path),
                "manifest": manifest.to_dict(),
            }
        )
        return 0

    manifest = store.load()
    report = store.validate(manifest)
    index_status = inspect_project_index(store, manifest)
    if args.project_command == "show":
        _json(
            {
                "ok": report.ok,
                "manifest_path": str(store.path),
                "manifest": manifest.to_dict(),
                "validation": report.to_dict(),
                "index": index_status.to_dict(),
            }
        )
        return 0 if report.ok else 1
    if args.project_command == "validate":
        _json(
            {
                "ok": report.ok,
                "validation": report.to_dict(),
                "index": index_status.to_dict(),
            }
        )
        return 0 if report.ok else 1
    if args.project_command == "index":
        if not report.ok:
            _json({"ok": False, "validation": report.to_dict()})
            return 1
        indexed = build_project_index(
            store,
            manifest,
            max_file_bytes=args.max_file_bytes,
        )
        _json({"ok": True, "index": indexed.to_dict()})
        return 0
    raise AssertionError("unreachable project command")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "capabilities":
            return _run_capabilities(args)
        return _run_project(args)
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        _json(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }
        )
        return 1


__all__ = ["main"]
