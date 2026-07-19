"""Bounded desktop façade for capabilities, projects and product artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from paperclaw.artifacts import (
    ArtifactCapacityError,
    ArtifactNotFoundError,
    FileArtifactStore,
)
from paperclaw.capabilities import default_capability_catalog
from paperclaw.projects import (
    ProjectKnowledgeRuntime,
    ProjectManifestStore,
    inspect_project_index,
)
from paperclaw.storage_safety import resolve_confined_path

from .contracts import DesktopPublicError

_MAX_ARTIFACT_ROWS = 100
_MAX_ARTIFACT_REVISIONS = 100
_MAX_PUBLIC_JSON_BYTES = 1_048_576


class DesktopProductService:
    """Project product operations safe to expose through the desktop bridge.

    All persistent operations are rooted in the caller-selected workspace.
    Provider credentials are never accepted or returned by this service.
    """

    def get_capabilities(
        self,
        maturity: str | None = None,
        surface: str | None = None,
    ) -> dict[str, object]:
        try:
            payload = default_capability_catalog().to_dict(
                maturity=maturity,
                surface=surface,
            )
        except ValueError as exc:
            raise DesktopPublicError("validation_error", str(exc)) from exc
        return self._public({"ok": True, "catalog": payload})

    def get_project_status(self, workspace: str) -> dict[str, object]:
        root = self._workspace(workspace)
        store = ProjectManifestStore(root)
        if not store.exists:
            return self._public(
                {
                    "ok": True,
                    "project": {
                        "state": "absent",
                        "workspace": str(root),
                        "manifest_path": str(store.path),
                        "manifest": None,
                        "validation": None,
                        "index": None,
                    },
                }
            )
        try:
            manifest = store.load()
            validation = store.validate(manifest)
            index = inspect_project_index(store, manifest)
        except (OSError, ValueError) as exc:
            return self._public(
                {
                    "ok": True,
                    "project": {
                        "state": "invalid",
                        "workspace": str(root),
                        "manifest_path": str(store.path),
                        "manifest": None,
                        "validation": {
                            "ok": False,
                            "issues": [
                                {
                                    "code": "manifest_invalid",
                                    "message": self._bounded(str(exc), 500),
                                    "path": ".paperclaw/project.json",
                                    "severity": "error",
                                }
                            ],
                        },
                        "index": None,
                    },
                }
            )
        state = "valid" if validation.ok else "invalid"
        if validation.ok and manifest.knowledge_paths:
            state = "current" if index.current else index.reason
        return self._public(
            {
                "ok": True,
                "project": {
                    "state": state,
                    "workspace": str(root),
                    "manifest_path": str(store.path),
                    "manifest": manifest.to_dict(),
                    "validation": validation.to_dict(),
                    "index": index.to_dict(),
                },
            }
        )

    def refresh_project_index(self, workspace: str) -> dict[str, object]:
        root = self._workspace(workspace)
        store = ProjectManifestStore(root)
        if not store.exists:
            raise DesktopPublicError(
                "project_not_found",
                "This workspace does not contain .paperclaw/project.json.",
            )
        try:
            manifest = store.load()
            validation = store.validate(manifest)
            if not validation.ok:
                raise DesktopPublicError(
                    "project_invalid",
                    "Project validation failed; fix the manifest before indexing.",
                )
            if not manifest.knowledge_paths:
                raise DesktopPublicError(
                    "project_knowledge_empty",
                    "The project does not declare any knowledge paths.",
                )
            snapshot, rebuilt = ProjectKnowledgeRuntime(
                store,
                manifest,
            ).refresh_if_stale()
        except DesktopPublicError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise DesktopPublicError(
                "project_refresh_failed",
                self._bounded(str(exc), 500),
            ) from exc
        return self._public(
            {
                "ok": True,
                "rebuilt": rebuilt,
                "knowledge": snapshot.to_dict(),
            }
        )

    def list_artifacts(
        self,
        workspace: str,
        filters: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        root = self._workspace(workspace)
        values = dict(filters or {})
        unknown = set(values) - {"artifact_type", "project_id", "limit"}
        if unknown:
            raise DesktopPublicError(
                "validation_error",
                f"Unknown artifact filters: {', '.join(sorted(unknown))}.",
            )
        limit = values.get("limit", 50)
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise DesktopPublicError(
                "validation_error", "Artifact limit must be an integer."
            )
        limit = min(_MAX_ARTIFACT_ROWS, max(1, limit))
        artifact_type = self._optional_identifier(
            values.get("artifact_type"), "artifact_type"
        )
        project_id = self._optional_identifier(
            values.get("project_id"), "project_id"
        )
        store = self._existing_artifact_store(root)
        if store is None:
            return self._public({"ok": True, "count": 0, "artifacts": []})
        try:
            artifacts = store.list_artifacts(
                artifact_type=artifact_type,
                project_id=project_id,
                limit=limit,
            )
        except DesktopPublicError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise DesktopPublicError(
                "artifact_list_failed", self._bounded(str(exc), 500)
            ) from exc
        return self._public(
            {
                "ok": True,
                "count": len(artifacts),
                "artifacts": [self._artifact_summary(item) for item in artifacts],
            }
        )

    def get_artifact(self, workspace: str, artifact_id: str) -> dict[str, object]:
        root = self._workspace(workspace)
        identifier = self._identifier(artifact_id, "artifact_id")
        store = self._existing_artifact_store(root)
        if store is None:
            raise DesktopPublicError("artifact_not_found", "Artifact was not found.")
        try:
            bundle = store.get_bundle(
                identifier,
                max_revisions=_MAX_ARTIFACT_REVISIONS,
            )
        except ArtifactNotFoundError as exc:
            raise DesktopPublicError("artifact_not_found", "Artifact was not found.") from exc
        except ArtifactCapacityError as exc:
            raise DesktopPublicError(
                "artifact_too_large",
                "Artifact revision history exceeds the desktop display limit.",
            ) from exc
        except DesktopPublicError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise DesktopPublicError(
                "artifact_read_failed", self._bounded(str(exc), 500)
            ) from exc
        return self._public({"ok": True, "bundle": bundle.to_dict()})

    def export_artifact(
        self,
        workspace: str,
        artifact_id: str,
        relative_path: str | None = None,
        revision_number: int | None = None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        root = self._workspace(workspace)
        identifier = self._identifier(artifact_id, "artifact_id")
        if revision_number is not None and (
            isinstance(revision_number, bool)
            or not isinstance(revision_number, int)
            or revision_number < 1
        ):
            raise DesktopPublicError(
                "validation_error", "revision_number must be a positive integer."
            )
        if not isinstance(overwrite, bool):
            raise DesktopPublicError(
                "validation_error", "overwrite must be a boolean."
            )
        path = self._relative_path(relative_path) if relative_path is not None else None
        store = self._existing_artifact_store(root)
        if store is None:
            raise DesktopPublicError("artifact_not_found", "Artifact was not found.")
        export_root = self._export_root(root)
        try:
            revision = store.get_revision(identifier, revision_number)
            resolved_path = path or self._default_export_path(
                identifier,
                revision.revision_number,
                revision.media_type,
            )
            exported = store.export_revision(
                identifier,
                export_root,
                resolved_path,
                revision_number=revision.revision_number,
                overwrite=overwrite,
            )
        except ArtifactNotFoundError as exc:
            raise DesktopPublicError("artifact_not_found", "Artifact was not found.") from exc
        except DesktopPublicError:
            raise
        except FileExistsError as exc:
            raise DesktopPublicError(
                "artifact_export_exists",
                "The export target already exists. Choose another name or allow overwrite.",
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise DesktopPublicError(
                "artifact_export_failed", self._bounded(str(exc), 500)
            ) from exc
        return self._public(
            {
                "ok": True,
                "artifact_id": identifier,
                "revision_number": revision.revision_number,
                "exported_path": str(exported),
                "workspace_relative_path": exported.relative_to(root).as_posix(),
            }
        )

    def get_overview(self, workspace: str) -> dict[str, object]:
        root = self._workspace(workspace)
        project = self.get_project_status(str(root))["project"]
        store = self._existing_artifact_store(root)
        if store is None:
            artifact_count = 0
            recent_artifacts = ()
        else:
            try:
                artifact_count = store.count_artifacts()
                recent_artifacts = store.list_artifacts(limit=10)
            except (OSError, RuntimeError, ValueError) as exc:
                raise DesktopPublicError(
                    "artifact_list_failed", self._bounded(str(exc), 500)
                ) from exc
        catalog = default_capability_catalog()
        maturity_counts: dict[str, int] = {}
        for item in catalog.capabilities:
            maturity_counts[item.maturity] = maturity_counts.get(item.maturity, 0) + 1
        return self._public(
            {
                "ok": True,
                "overview": {
                    "project": project,
                    "artifact_count": artifact_count,
                    "recent_artifacts": [
                        self._artifact_summary(item) for item in recent_artifacts
                    ],
                    "capability_count": len(catalog.capabilities),
                    "capability_maturity": maturity_counts,
                },
            }
        )

    @staticmethod
    def _workspace(value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise DesktopPublicError(
                "validation_error", "Workspace must be a non-empty path."
            )
        raw = Path(value).expanduser()
        if raw.is_symlink():
            raise DesktopPublicError(
                "workspace_policy_denied",
                "Product operations do not accept a symbolic-link workspace.",
            )
        try:
            resolved = raw.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise DesktopPublicError(
                "workspace_not_found", "Workspace does not exist or cannot be opened."
            ) from exc
        if not resolved.is_dir():
            raise DesktopPublicError(
                "workspace_not_found", "Workspace must be an existing directory."
            )
        return resolved

    @staticmethod
    def _existing_artifact_store(workspace: Path) -> FileArtifactStore | None:
        unresolved = workspace / ".paperclaw" / "artifacts"
        database_unresolved = unresolved / "artifacts.sqlite3"
        if unresolved.is_symlink() or database_unresolved.is_symlink():
            raise DesktopPublicError(
                "artifact_policy_denied",
                "Artifact storage must not be a symbolic link.",
            )
        try:
            root = resolve_confined_path(
                workspace,
                unresolved,
                strict=False,
                label="artifact storage",
            )
        except ValueError as exc:
            raise DesktopPublicError(
                "artifact_policy_denied",
                "Artifact storage escapes the selected workspace.",
            ) from exc
        database = root / "artifacts.sqlite3"
        if database.is_symlink():
            raise DesktopPublicError(
                "artifact_policy_denied",
                "Artifact database must not be a symbolic link.",
            )
        if not database.is_file():
            return None
        try:
            return FileArtifactStore(root, confinement_root=workspace)
        except ValueError as exc:
            raise DesktopPublicError(
                "artifact_policy_denied",
                "Artifact storage violates workspace policy.",
            ) from exc

    @staticmethod
    def _export_root(workspace: Path) -> Path:
        unresolved = workspace / ".paperclaw" / "exports"
        if unresolved.is_symlink():
            raise DesktopPublicError(
                "artifact_policy_denied",
                "Artifact export directory must not be a symbolic link.",
            )
        try:
            resolved = resolve_confined_path(
                workspace,
                unresolved,
                strict=False,
                label="artifact export directory",
            )
            resolved.mkdir(parents=True, exist_ok=True)
            return resolve_confined_path(
                workspace,
                resolved,
                strict=True,
                label="artifact export directory",
            )
        except (OSError, ValueError) as exc:
            raise DesktopPublicError(
                "artifact_policy_denied",
                "Artifact export directory escapes the selected workspace.",
            ) from exc

    @staticmethod
    def _identifier(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 200:
            raise DesktopPublicError(
                "validation_error", f"{name} must be a bounded identifier."
            )
        allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
        if any(char not in allowed for char in value):
            raise DesktopPublicError(
                "validation_error", f"{name} contains unsupported characters."
            )
        return value

    def _optional_identifier(self, value: Any, name: str) -> str | None:
        if value in (None, ""):
            return None
        return self._identifier(value, name)

    @staticmethod
    def _relative_path(value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise DesktopPublicError(
                "validation_error", "Export path must be bounded and non-empty."
            )
        normalized = value.strip().replace("\\", "/")
        parts = normalized.split("/")
        if (
            normalized.startswith("/")
            or ".." in parts
            or any(part in {"", "."} for part in parts)
        ):
            raise DesktopPublicError(
                "validation_error",
                "Export path must stay inside the workspace export directory.",
            )
        return normalized

    @staticmethod
    def _default_export_path(
        artifact_id: str,
        revision_number: int,
        media_type: str,
    ) -> str:
        suffix = {
            "text/markdown": ".md",
            "text/plain": ".txt",
            "application/json": ".json",
            "text/html": ".html",
        }.get(media_type, ".bin")
        return f"{artifact_id}-r{revision_number}{suffix}"

    @staticmethod
    def _artifact_summary(item: Any) -> dict[str, object]:
        return {
            "artifact_id": item.artifact_id,
            "artifact_type": item.artifact_type,
            "title": item.title,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "latest_revision_number": item.latest_revision_number,
            "source": item.source.to_dict(),
        }

    @staticmethod
    def _public(payload: dict[str, object]) -> dict[str, object]:
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise DesktopPublicError(
                "runtime_error", "Desktop product response is not serializable."
            ) from exc
        if len(encoded) > _MAX_PUBLIC_JSON_BYTES:
            raise DesktopPublicError(
                "response_too_large",
                "Desktop product response exceeds the public response limit.",
            )
        return payload

    @staticmethod
    def _bounded(value: str, limit: int) -> str:
        return value if len(value) <= limit else value[: max(0, limit - 1)] + "…"


__all__ = ["DesktopProductService"]
