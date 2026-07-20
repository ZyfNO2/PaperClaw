"""PaperClaw project workspace, knowledge and extension lifecycle."""

from .extension_runtime import (
    ActivatedConnector,
    ActivatedSkill,
    ConnectorFactory,
    ConnectorRuntime,
    ProjectExtensionActivation,
    ProjectExtensionActivator,
)
from .extensions import (
    ExtensionKind,
    ExtensionPermissions,
    ExtensionRegistrySnapshot,
    ProjectExtensionDescriptor,
    ProjectExtensionRegistry,
    TrustSource,
)
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
    "ActivatedConnector",
    "ActivatedSkill",
    "ConnectorFactory",
    "ConnectorRuntime",
    "ExtensionKind",
    "ExtensionPermissions",
    "ExtensionRegistrySnapshot",
    "ProjectExtensionActivation",
    "ProjectExtensionActivator",
    "ProjectExtensionDescriptor",
    "ProjectExtensionRegistry",
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
    "TrustSource",
    "build_project_index",
    "discover_project_manifest",
    "inspect_project_index",
    "project_index_database",
]
