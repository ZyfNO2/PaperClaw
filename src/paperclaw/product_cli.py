"""Product-foundation CLI commands kept separate from the legacy runtime parser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from paperclaw.artifacts import ArtifactSourceLinks, FileArtifactStore
from paperclaw.capabilities import default_capability_catalog
from paperclaw.projects import (
    ProjectIndexPolicy,
    ProjectKnowledgeRuntime,
    ProjectKnowledgeWatcher,
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

    project_refresh = project_subparsers.add_parser("refresh")
    project_refresh.add_argument(
        "--policy",
        choices=tuple(item.value for item in ProjectIndexPolicy),
        default=ProjectIndexPolicy.REQUIRE_CURRENT.value,
    )
    project_refresh.add_argument("--max-file-bytes", type=int, default=5_000_000)

    project_watch = project_subparsers.add_parser("watch")
    project_watch.add_argument("--once", action="store_true", required=True)
    project_watch.add_argument("--rebuild-on-change", action="store_true")
    project_watch.add_argument("--max-file-bytes", type=int, default=5_000_000)

    artifact = subparsers.add_parser("artifact")
    artifact.add_argument("--workspace", type=Path, default=Path.cwd())
    artifact_subparsers = artifact.add_subparsers(
        dest="artifact_command", required=True
    )

    artifact_create = artifact_subparsers.add_parser("create")
    artifact_create.add_argument("--type", required=True, dest="artifact_type")
    artifact_create.add_argument("--title", required=True)
    artifact_create.add_argument("--file", required=True, type=Path)
    artifact_create.add_argument("--media-type", required=True)
    artifact_create.add_argument("--idempotency-key", required=True)
    artifact_create.add_argument("--project-id")
    artifact_create.add_argument("--run-id")
    artifact_create.add_argument("--task-id")
    artifact_create.add_argument("--trace-id")

    artifact_list = artifact_subparsers.add_parser("list")
    artifact_list.add_argument("--type", dest="artifact_type")
    artifact_list.add_argument("--project-id")
    artifact_list.add_argument("--limit", type=int, default=200)

    artifact_show = artifact_subparsers.add_parser("show")
    artifact_show.add_argument("artifact_id")

    artifact_revise = artifact_subparsers.add_parser("revise")
    artifact_revise.add_argument("artifact_id")
    artifact_revise.add_argument("--file", required=True, type=Path)
    artifact_revise.add_argument("--media-type", required=True)
    artifact_revise.add_argument("--idempotency-key", required=True)
    artifact_revise.add_argument("--message")

    artifact_export = artifact_subparsers.add_parser("export")
    artifact_export.add_argument("artifact_id")
    artifact_export.add_argument("--destination-root", required=True, type=Path)
    artifact_export.add_argument("--path", required=True, dest="relative_path")
    artifact_export.add_argument("--revision", type=int)
    artifact_export.add_argument("--overwrite", action="store_true")
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
    if args.project_command == "refresh":
        if not report.ok:
            _json({"ok": False, "validation": report.to_dict()})
            return 1
        runtime = ProjectKnowledgeRuntime(
            store,
            manifest,
            policy=args.policy,
            max_file_bytes=args.max_file_bytes,
        )
        snapshot, rebuilt = runtime.refresh_if_stale()
        _json(
            {
                "ok": True,
                "rebuilt": rebuilt,
                "knowledge": snapshot.to_dict(),
            }
        )
        return 0
    if args.project_command == "watch":
        runtime = ProjectKnowledgeRuntime(
            store,
            manifest,
            max_file_bytes=args.max_file_bytes,
        )
        watcher = ProjectKnowledgeWatcher(
            runtime,
            rebuild_on_change=args.rebuild_on_change,
        )
        event = watcher.poll_once()
        _json(
            {
                "ok": True,
                "changed": event is not None,
                "event": (
                    {
                        "previous_reason": event.previous_reason,
                        "current_reason": event.current_reason,
                        "rebuilt": event.rebuilt,
                        "elapsed_seconds": event.elapsed_seconds,
                    }
                    if event is not None
                    else None
                ),
                "knowledge": runtime.inspect().to_dict(),
            }
        )
        return 0
    raise AssertionError("unreachable project command")


def _artifact_store(args: argparse.Namespace) -> FileArtifactStore:
    workspace = Path(args.workspace).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("workspace must be a directory")
    return FileArtifactStore(workspace / ".paperclaw" / "artifacts")


def _workspace_file(workspace: Path, value: Path) -> Path:
    raw = value if value.is_absolute() else workspace / value
    resolved = raw.expanduser().resolve(strict=True)
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("artifact source file must stay inside workspace") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError("artifact source must be a regular non-symlink file")
    return resolved


def _run_artifact(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve(strict=True)
    store = _artifact_store(args)
    if args.artifact_command == "create":
        source_file = _workspace_file(workspace, args.file)
        artifact, revision, created = store.create_artifact(
            idempotency_key=args.idempotency_key,
            artifact_type=args.artifact_type,
            title=args.title,
            media_type=args.media_type,
            content=source_file.read_bytes(),
            source=ArtifactSourceLinks(
                project_id=args.project_id,
                run_id=args.run_id,
                task_id=args.task_id,
                trace_id=args.trace_id,
            ),
            metadata={"source_path": source_file.relative_to(workspace).as_posix()},
        )
        _json(
            {
                "ok": True,
                "created": created,
                "artifact": artifact.to_dict(),
                "revision": revision.to_dict(),
            }
        )
        return 0
    if args.artifact_command == "list":
        artifacts = store.list_artifacts(
            artifact_type=args.artifact_type,
            project_id=args.project_id,
            limit=args.limit,
        )
        _json(
            {
                "ok": True,
                "count": len(artifacts),
                "artifacts": [item.to_dict() for item in artifacts],
            }
        )
        return 0
    if args.artifact_command == "show":
        _json({"ok": True, "bundle": store.get_bundle(args.artifact_id).to_dict()})
        return 0
    if args.artifact_command == "revise":
        source_file = _workspace_file(workspace, args.file)
        revision, created = store.add_revision(
            args.artifact_id,
            idempotency_key=args.idempotency_key,
            media_type=args.media_type,
            content=source_file.read_bytes(),
            message=args.message,
            metadata={"source_path": source_file.relative_to(workspace).as_posix()},
        )
        _json({"ok": True, "created": created, "revision": revision.to_dict()})
        return 0
    if args.artifact_command == "export":
        exported = store.export_revision(
            args.artifact_id,
            args.destination_root,
            args.relative_path,
            revision_number=args.revision,
            overwrite=args.overwrite,
        )
        _json({"ok": True, "exported_path": str(exported)})
        return 0
    raise AssertionError("unreachable artifact command")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "capabilities":
            return _run_capabilities(args)
        if args.command == "project":
            return _run_project(args)
        return _run_artifact(args)
    except (FileExistsError, FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        _json(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }
        )
        return 1


__all__ = ["main"]
