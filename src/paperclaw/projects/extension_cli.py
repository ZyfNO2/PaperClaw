"""CLI for project-scoped extension registry management."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .extensions import (
    ExtensionPermissions,
    ProjectExtensionDescriptor,
    ProjectExtensionRegistry,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-project-extensions")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list")
    listing.add_argument("--kind", choices=("skill", "connector"))
    listing.add_argument("--enabled", choices=("true", "false"))

    commands.add_parser("validate")
    audit = commands.add_parser("audit")
    audit.add_argument("--limit", type=int, default=200)

    for command_name, kind in (
        ("register-skill", "skill"),
        ("register-connector", "connector"),
    ):
        command = commands.add_parser(command_name)
        command.set_defaults(kind=kind)
        command.add_argument("--id", required=True)
        command.add_argument("--version", required=True)
        command.add_argument("--entrypoint", required=True)
        command.add_argument(
            "--trust-source",
            choices=("builtin", "verified", "project", "untrusted"),
            default="project",
        )
        command.add_argument("--enabled", action="store_true")
        command.add_argument("--tool", action="append", default=[])
        command.add_argument("--read-path", action="append", default=[])
        command.add_argument("--write-path", action="append", default=[])
        command.add_argument("--network-host", action="append", default=[])
        command.add_argument("--auth-ref")
        command.add_argument("--replace", action="store_true")

    for command_name in ("enable", "disable", "remove"):
        command = commands.add_parser(command_name)
        command.add_argument("extension_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = args.workspace.expanduser().resolve(strict=True)
    registry = ProjectExtensionRegistry(workspace)

    if args.command == "list":
        enabled = None if args.enabled is None else args.enabled == "true"
        payload: dict[str, object] = {
            "schema_version": 1,
            "extensions": [
                item.to_dict()
                for item in registry.list(kind=args.kind, enabled=enabled)
            ],
        }
    elif args.command == "validate":
        issues = registry.validate()
        payload = {"ok": not issues, "issues": list(issues)}
    elif args.command == "audit":
        payload = {
            "events": list(registry.audit_events(limit=args.limit)),
            "invocations": list(registry.invocation_events(limit=args.limit)),
        }
    elif args.command in {"register-skill", "register-connector"}:
        descriptor = ProjectExtensionDescriptor(
            extension_id=args.id,
            kind=args.kind,
            version=args.version,
            entrypoint=args.entrypoint,
            enabled=args.enabled,
            trust_source=args.trust_source,
            auth_ref=args.auth_ref,
            permissions=ExtensionPermissions(
                tools=tuple(args.tool),
                read_paths=tuple(args.read_path),
                write_paths=tuple(args.write_path),
                network_hosts=tuple(args.network_host),
            ),
        )
        payload = registry.register(
            descriptor, replace_existing=args.replace
        ).to_dict()
    elif args.command == "enable":
        payload = registry.set_enabled(args.extension_id, True).to_dict()
    elif args.command == "disable":
        payload = registry.set_enabled(args.extension_id, False).to_dict()
    else:
        payload = registry.remove(args.extension_id).to_dict()

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 1 if args.command == "validate" and not payload["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
