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
"""

from __future__ import annotations

from paperclaw.runtime.flow_contracts import (
    FlowResumePoint,
    RuntimeServices,
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
    "COMPLETED_NODE_ID",
    "CompletedNode",
    "FlowResumePoint",
    "IdentifiedNode",
    "NodeRegistry",
    "RegistryMismatch",
    "RuntimeServices",
    "compute_registry_hash",
]
