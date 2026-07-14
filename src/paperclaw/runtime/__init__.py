"""PaperClaw Runtime adapter layer.

This package adapts the vendored PocketFlow Node/Flow primitives to the
PaperClaw Context / Session / Permission / Trace runtime without modifying
``src/pocketflow/__init__.py`` (per Addendum §1).

Modules:

- ``node_registry``: stable node identity + CompletedNode + registry hash.
  P0-A deliverable.
- ``flow_contracts``: FlowResumePoint + RuntimeServices dataclasses shared
  by the InstrumentedFlowRunner (P0-B) and Checkpoint wiring (P0-C).
  P0-A only ships the dataclasses; the runner itself is P0-B.
- ``error_codes``: stable error code constants + ``classify_exception``
  helper for ``node.failed`` event payloads. P0-B deliverable; P0-C adds
  ``RECOVERY_REQUIRED`` and ``INCOMPATIBLE_FLOW_DEFINITION`` for the
  safe-resume decision.
- ``flow_runner``: ``InstrumentedFlowRunner`` wrapping PocketFlow Flow with
  event emission, cancellation, and resume entry-point resolution. P0-B
  deliverable. Parity mode delegates to native ``Flow.run`` when all
  services are None (Addendum PB5 hard gate). P0-C wires the real
  ``CheckpointWriter.commit_checkpoint`` call after each ``node.completed``
  event and emits ``flow.resumed`` when entering from a resume point.
- ``checkpoint``: ``CheckpointWriter`` Protocol + ``SqliteCheckpointWriter``
  + ``InMemoryCheckpointWriter`` test double. P0-C deliverable.
- ``resume``: ``ResumeDecision`` + ``evaluate_resume_safety`` implementing
  Addendum §5.3 rules (registry hash, pending operations, file snapshots).
  P0-C deliverable.
- ``file_snapshot``: ``FileSnapshotVerifier`` — hashlib-based file state
  verification for SOP §10.1 rule "关键文件 hash / existence 重新验证通过".
  Phase E deliverable.
- ``resume_coordinator``: ``ResumeCoordinator`` + ``build_pending_operations``
  — end-to-end resume decision entry that composes SessionService read-side
  + NodeRegistry + FileSnapshotVerifier + evaluate_resume_safety.
  Phase E deliverable.
"""

from __future__ import annotations

from paperclaw.runtime.checkpoint import (
    CheckpointWriter,
    InMemoryCheckpointWriter,
    SqliteCheckpointWriter,
)
from paperclaw.runtime.error_codes import (
    ALL_ERROR_CODES,
    CANCELLATION_REQUESTED,
    INCOMPATIBLE_FLOW_DEFINITION,
    NODE_EXEC_FAILED,
    NODE_IDENTITY_MISSING,
    NODE_POST_FAILED,
    NODE_PREP_FAILED,
    RECOVERY_REQUIRED,
    RESUME_REGISTRY_MISMATCH,
    classify_exception,
)
from paperclaw.runtime.file_snapshot import FileSnapshotVerifier
from paperclaw.runtime.flow_contracts import (
    FlowResumePoint,
    RuntimeServices,
)
from paperclaw.runtime.flow_runner import (
    InstrumentedFlowRunner,
    NodeIdentityMissingError,
    ResumeRegistryMismatchError,
)
from paperclaw.runtime.node_registry import (
    COMPLETED_NODE_ID,
    CompletedNode,
    IdentifiedNode,
    NodeRegistry,
    RegistryMismatch,
    compute_registry_hash,
)
from paperclaw.runtime.resume import (
    ResumeDecision,
    TERMINAL_OPERATION_STATES,
    evaluate_resume_safety,
)
from paperclaw.runtime.resume_coordinator import (
    ACTIVE_TASK_STATUSES,
    OPERATION_STARTED_EVENT,
    OPERATION_TERMINAL_EVENTS,
    SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS,
    ResumeCoordinator,
    build_pending_operations,
)

__all__ = [
    "ACTIVE_TASK_STATUSES",
    "ALL_ERROR_CODES",
    "CANCELLATION_REQUESTED",
    "CheckpointWriter",
    "COMPLETED_NODE_ID",
    "CompletedNode",
    "FileSnapshotVerifier",
    "FlowResumePoint",
    "IdentifiedNode",
    "InMemoryCheckpointWriter",
    "INCOMPATIBLE_FLOW_DEFINITION",
    "InstrumentedFlowRunner",
    "NodeIdentityMissingError",
    "NodeRegistry",
    "NODE_EXEC_FAILED",
    "NODE_IDENTITY_MISSING",
    "NODE_POST_FAILED",
    "NODE_PREP_FAILED",
    "OPERATION_STARTED_EVENT",
    "OPERATION_TERMINAL_EVENTS",
    "RECOVERY_REQUIRED",
    "RegistryMismatch",
    "RESUME_REGISTRY_MISMATCH",
    "ResumeCoordinator",
    "ResumeDecision",
    "ResumeRegistryMismatchError",
    "RuntimeServices",
    "SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS",
    "SqliteCheckpointWriter",
    "TERMINAL_OPERATION_STATES",
    "build_pending_operations",
    "classify_exception",
    "compute_registry_hash",
    "evaluate_resume_safety",
]
