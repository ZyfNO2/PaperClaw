"""Bounded long-term memory and user-profile support."""

from .runtime import MemoryRuntimeComponents, MemoryRuntimeSettings, build_memory_runtime
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
    "build_memory_runtime",
]
