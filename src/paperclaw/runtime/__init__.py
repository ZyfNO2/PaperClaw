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
  helper for ``node.failed`` event payloads. P0-B deliverable.
- ``flow_runner``: ``InstrumentedFlowRunner`` wrapping PocketFlow Flow with
  event emission, cancellation, and resume entry-point resolution. P0-B
  deliverable. Parity mode delegates to native ``Flow.run`` when all
  services are None (Addendum PB5 hard gate).
"""

from __future__ import annotations

from paperclaw.runtime.error_codes import (
    ALL_ERROR_CODES,
    CANCELLATION_REQUESTED,
    NODE_EXEC_FAILED,
    NODE_IDENTITY_MISSING,
    NODE_POST_FAILED,
    NODE_PREP_FAILED,
    RESUME_REGISTRY_MISMATCH,
    classify_exception,
)
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

__all__ = [
    "ALL_ERROR_CODES",
    "CANCELLATION_REQUESTED",
    "COMPLETED_NODE_ID",
    "CompletedNode",
    "FlowResumePoint",
    "IdentifiedNode",
    "InstrumentedFlowRunner",
    "NodeIdentityMissingError",
    "NodeRegistry",
    "NODE_EXEC_FAILED",
    "NODE_IDENTITY_MISSING",
    "NODE_POST_FAILED",
    "NODE_PREP_FAILED",
    "RegistryMismatch",
    "RESUME_REGISTRY_MISMATCH",
    "ResumeRegistryMismatchError",
    "RuntimeServices",
    "classify_exception",
    "compute_registry_hash",
]
