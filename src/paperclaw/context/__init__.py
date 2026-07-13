"""PaperClaw Context Engineering package (v0.04).

This package implements the layered Context Runtime: structured ContextItem
contracts, SQLite persistence with append-only SessionEvent log, role-scoped
ContextBuilder, deterministic compaction, and step-boundary safe resume.

Design boundaries:
- The context package owns data contracts, persistence, builder, compaction,
  budget, and resume logic.
- It must NOT depend on `paperclaw.multiagent` internal scheduler state; the
  MultiAgent layer is a consumer, not a dependency.
- Long-term auto memory, vector retrieval, and arbitrary crash recovery are
  explicitly out of scope (deferred to v0.04.1+).
"""

from paperclaw.context.builder import (
    ContextBudgetExhausted,
    ContextBuilder,
    ContextBuilderError,
    EXCLUSION_BUDGET,
    EXCLUSION_CONFLICT,
    EXCLUSION_DEDUPLICATION,
    EXCLUSION_EXPIRED,
    EXCLUSION_SCOPE,
    EXCLUSION_SUPERSEDED,
    EXCLUSION_TRUST_VIOLATION,
    ROLE_COORDINATOR,
    ROLE_REVIEWER,
    ROLE_WORKER,
    RoleContextView,
)
from paperclaw.context.contracts import (
    Checkpoint,
    CompactionResult,
    ContextBudget,
    ContextItem,
    ContextSnapshot,
    ContextSource,
    SessionEvent,
)
from paperclaw.context.migrations import MigrationRunner, SCHEMA_VERSION_V1
from paperclaw.context.repository import Repository, SQLiteRepository
from paperclaw.context.session import (
    EventSink,
    NullEventSink,
    SessionService,
    SqliteEventSink,
    open_session,
    reopen_session,
)

__all__ = [
    "Checkpoint",
    "CompactionResult",
    "ContextBudget",
    "ContextBudgetExhausted",
    "ContextBuilder",
    "ContextBuilderError",
    "ContextItem",
    "ContextSnapshot",
    "ContextSource",
    "EventSink",
    "EXCLUSION_BUDGET",
    "EXCLUSION_CONFLICT",
    "EXCLUSION_DEDUPLICATION",
    "EXCLUSION_EXPIRED",
    "EXCLUSION_SCOPE",
    "EXCLUSION_SUPERSEDED",
    "EXCLUSION_TRUST_VIOLATION",
    "MigrationRunner",
    "NullEventSink",
    "ROLE_COORDINATOR",
    "ROLE_REVIEWER",
    "ROLE_WORKER",
    "Repository",
    "RoleContextView",
    "SCHEMA_VERSION_V1",
    "SQLiteRepository",
    "SessionEvent",
    "SessionService",
    "SqliteEventSink",
    "open_session",
    "reopen_session",
]
