"""Bounded long-term memory and user-profile support."""

from .runtime import MemoryRuntimeComponents, MemoryRuntimeSettings, build_memory_runtime
from .context_source import StructuredMemoryContextSource
from .contracts import (
    MemoryBoundaryError,
    MemoryContractError,
    MemoryConflictDecision,
    MemoryConflictDecisionRecord,
    MemoryItem,
    MemoryKind,
    MemoryScope,
    MemorySourceRef,
    MemoryTrustError,
    MemorySnapshot as StructuredMemorySnapshot,
)
from .repository import MemoryRepository, MemoryRepositoryProtocol
from .service import MemoryBudget, MemoryService
from .scoped import MemoryStoreProtocol, ProjectMemoryPaths, ProjectScopedMemoryStore
from .source import (
    FrozenFoundationalContextSource,
    ProjectInstructionLoader,
    ProjectInstructionSnapshot,
)
from .store import (
    FileMemoryStore,
    MemoryCapacityError,
    MemoryEntry,
    MemoryLockTimeout,
    MemoryMatchError,
    MemoryPolicy,
    MemoryPrivacyError,
    MemorySnapshot,
    MemoryStoreError,
)
from .tool import MemoryTool

__all__ = [
    "FileMemoryStore",
    "FrozenFoundationalContextSource",
    "MemoryCapacityError",
    "MemoryEntry",
    "MemoryLockTimeout",
    "MemoryMatchError",
    "MemoryPolicy",
    "MemoryPrivacyError",
    "MemoryBoundaryError",
    "MemoryContractError",
    "MemoryConflictDecision",
    "MemoryConflictDecisionRecord",
    "MemoryItem",
    "MemoryKind",
    "MemoryScope",
    "MemorySourceRef",
    "MemoryTrustError",
    "MemoryBudget",
    "MemoryRepository",
    "MemoryRepositoryProtocol",
    "MemoryService",
    "MemoryRuntimeComponents",
    "MemoryRuntimeSettings",
    "MemorySnapshot",
    "MemoryStoreError",
    "MemoryStoreProtocol",
    "MemoryTool",
    "ProjectInstructionLoader",
    "ProjectInstructionSnapshot",
    "ProjectMemoryPaths",
    "ProjectScopedMemoryStore",
    "StructuredMemoryContextSource",
    "StructuredMemorySnapshot",
    "build_memory_runtime",
]
