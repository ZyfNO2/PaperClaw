"""PaperClaw project workspace manifest and knowledge lifecycle."""

from .indexing import (
    ProjectIndexReport,
    ProjectIndexStatus,
    ProjectKnowledgeFile,
    build_project_index,
    inspect_project_index,
    project_index_database,
)
from .manifest import (
    ProjectManifest,
    ProjectManifestStore,
    ProjectValidationIssue,
    ProjectValidationReport,
    discover_project_manifest,
)
from .runtime import (
    ProjectIndexPolicy,
    ProjectKnowledgeRuntime,
    ProjectKnowledgeSnapshot,
    ProjectKnowledgeUnavailableError,
    ProjectKnowledgeWatchEvent,
    ProjectKnowledgeWatcher,
)

__all__ = [
    "ProjectIndexPolicy",
    "ProjectIndexReport",
    "ProjectIndexStatus",
    "ProjectKnowledgeFile",
    "ProjectKnowledgeRuntime",
    "ProjectKnowledgeSnapshot",
    "ProjectKnowledgeUnavailableError",
    "ProjectKnowledgeWatchEvent",
    "ProjectKnowledgeWatcher",
    "ProjectManifest",
    "ProjectManifestStore",
    "ProjectValidationIssue",
    "ProjectValidationReport",
    "build_project_index",
    "discover_project_manifest",
    "inspect_project_index",
    "project_index_database",
]
