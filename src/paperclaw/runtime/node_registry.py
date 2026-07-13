"""Stable Node identity for the PaperClaw runtime.

PocketFlow's native graph wiring relies on Python object references. That is
fine for in-process execution but breaks persistence and resume:

- Python object addresses are not stable across processes.
- Anonymous ``Node()`` terminals have no semantic name.
- A Checkpoint cannot record ``next_node_id`` if ``id(node)`` is the only
  identity available.

This module introduces PaperClaw-side identity (per Addendum §3):

- ``IdentifiedNode``: a Protocol that requires ``node_id: str``. Nodes opt in
  by setting ``node_id`` as a class attribute or instance attribute.
- ``CompletedNode``: PaperClaw's own terminal node with ``node_id = "completed"``.
  Replaces the anonymous ``Node()`` terminals used by ``build_react_flow``.
- ``NodeRegistry``: bidirectional ``node_id <-> Node`` mapping plus a stable
  hash of the registered node IDs. The hash is recorded in Checkpoints so a
  resume can detect an incompatible Flow definition (Addendum §5.4).
- ``RegistryMismatch``: raised when a Checkpoint's ``node_registry_hash`` does
  not match the current runtime registry. Resume MUST stop, not silently
  map to the "closest" node name.

Stable ID conventions (Addendum §3.2):

- ``decide`` for the action-selection node.
- ``tool:<tool_name>`` for execute-tool nodes (e.g. ``tool:file_read``).
- ``verify_done`` for the verification gate.
- ``reflect`` for the reflection node.
- ``completed`` for the terminal node.

Renaming a node ID is a schema/replay-compatibility change. The hash makes
such a change visible at resume time.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Protocol, runtime_checkable

from pocketflow import Node


# ---------------------------------------------------------------------------
# Identity protocol
# ---------------------------------------------------------------------------


#: Stable ID of the canonical terminal node. Addendum §3.4.
COMPLETED_NODE_ID = "completed"


@runtime_checkable
class IdentifiedNode(Protocol):
    """Anything that exposes a stable ``node_id``.

    The Protocol is ``runtime_checkable`` so the NodeRegistry can assert
    ``isinstance(node, IdentifiedNode)`` at registration time without
    requiring a concrete base class. PocketFlow's ``Node`` does not know
    about ``node_id``; PaperClaw adds it via a class attribute.

    Allowed implementations (Addendum §3.3):

    - Class attribute: ``class DecideActionNode(Node): node_id = "decide"``
    - Instance attribute set in ``__init__``: ``self.node_id = f"tool:{name}"``
    - Registry-based: ``registry.register("decide", decide)``

    The Registry supports all three; only the resulting ``node_id`` matters.
    """

    node_id: str


# ---------------------------------------------------------------------------
# CompletedNode
# ---------------------------------------------------------------------------


class CompletedNode(Node):
    """PaperClaw's explicit terminal node.

    Replaces the anonymous ``Node()`` terminals used by the original
    ``build_react_flow``. Has a stable ``node_id = "completed"`` so a
    Checkpoint can record that the Flow has reached its terminal state.

    Requirements (Addendum §3.4):

    - ``completed`` is the stable terminal; only one per Flow definition.
    - The last business node MUST have committed before transitioning here.
    - This node MUST NOT produce files, Shell, or external API side effects.
    - ``flow.stopped`` events MUST reference ``completed`` or a failure node.

    The ``post`` hook sets ``shared["stop_reason"]`` to ``"done"`` only if no
    earlier node has set a more specific reason (e.g. ``"cancelled"``,
    ``"timeout"``, ``"verification_failed"``). This preserves the existing
    stop-reason semantics of v0.01–v0.03.
    """

    node_id = COMPLETED_NODE_ID

    def prep(self, shared: dict) -> Any:  # noqa: D401 - PocketFlow hook
        # Nothing to prepare; the terminal node performs no I/O.
        return None

    def exec(self, prep_res: Any) -> Any:  # noqa: D401 - PocketFlow hook
        return None

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        # Preserve a more specific stop_reason if set earlier; only fall back
        # to "done" when no reason was recorded. Returning None ends the Flow.
        shared["stop_reason"] = shared.get("stop_reason") or "done"
        return None


# ---------------------------------------------------------------------------
# NodeRegistry
# ---------------------------------------------------------------------------


class RegistryMismatch(Exception):
    """Raised when a Checkpoint's node registry hash does not match the
    current runtime registry.

    Per Addendum §5.4 the runtime MUST stop automatic resume and surface both
    the stored and current hashes. Silently mapping to the "closest" node
    name is explicitly forbidden.
    """

    def __init__(self, stored_hash: str, current_hash: str, message: str | None = None):
        self.stored_hash = stored_hash
        self.current_hash = current_hash
        super().__init__(
            message
            or (
                f"node registry mismatch: stored={stored_hash} current={current_hash} "
                "(incompatible Flow definition; resume refused)"
            )
        )


class NodeRegistry:
    """Bidirectional ``node_id <-> Node`` mapping with a stable hash.

    The registry is the single source of truth for node identity in a Flow
    definition. ``InstrumentedFlowRunner`` (P0-B) uses it to:

    - Resolve ``next_node_id`` from a Checkpoint back to a Node instance.
    - Record ``node_registry_hash`` in new Checkpoints.
    - Detect incompatible Flow definitions at resume time (Addendum §5.4).

    Construction rules:

    - ``register(node_id, node)`` is idempotent for the same pair.
    - Re-registering an existing ``node_id`` with a DIFFERENT Node instance
      raises ``ValueError`` — that is a Flow-definition change, not a
      registry update.
    - A Node that exposes ``node_id`` (class or instance attribute) can be
      added via ``add(node)``; the registry reads ``node.node_id``.
    - The hash is computed from the sorted ``node_id`` list, not from the
      Node objects. Renaming or adding/removing a node changes the hash;
      reordering the same set of nodes does not.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, Node] = {}
        self._by_node: dict[int, str] = {}
        # Cached hash; recomputed on mutation. ``None`` means "dirty".
        self._hash_cache: str | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, node_id: str, node: Node) -> None:
        """Register one node under ``node_id``.

        Idempotent for ``(node_id, node)`` pairs. Raises ``ValueError`` if
        ``node_id`` is already bound to a different Node instance, or if the
        Node instance is already registered under a different ID.
        """
        self._validate_id(node_id)
        existing = self._by_id.get(node_id)
        if existing is not None and existing is not node:
            raise ValueError(
                f"node_id {node_id!r} is already registered to a different "
                f"Node instance ({existing!r})"
            )
        existing_id = self._by_node.get(id(node))
        if existing_id is not None and existing_id != node_id:
            raise ValueError(
                f"Node instance {node!r} is already registered under "
                f"node_id {existing_id!r}; cannot rebind to {node_id!r}"
            )
        self._by_id[node_id] = node
        self._by_node[id(node)] = node_id
        self._hash_cache = None

    def add(self, node: Node) -> str:
        """Register a Node that exposes its own ``node_id``.

        Returns the registered ``node_id``. Raises ``ValueError`` if the Node
        does not expose ``node_id`` or the attribute is empty.
        """
        node_id = getattr(node, "node_id", None)
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(
                f"Node {node!r} does not expose a non-empty string node_id; "
                "use register(node_id, node) instead"
            )
        self.register(node_id, node)
        return node_id

    def add_many(self, nodes: Iterable[Node]) -> list[str]:
        """Register multiple nodes that expose their own ``node_id``."""
        ids: list[str] = []
        for node in nodes:
            ids.append(self.add(node))
        return ids

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, node_id: str) -> Node:
        """Return the Node registered under ``node_id``.

        Raises ``KeyError`` if not found. Callers that want to detect an
        unknown ``next_node_id`` at resume time (Addendum §5.3) should catch
        ``KeyError`` and treat it as ``recovery_required``.
        """
        return self._by_id[node_id]

    def get_id(self, node: Node) -> str:
        """Return the ``node_id`` registered for ``node``.

        Raises ``KeyError`` if the Node is not in this registry. Uses
        ``id(node)`` for the reverse lookup because PocketFlow's ``__eq__``
        is the default identity equality.
        """
        return self._by_node[id(node)]

    def __contains__(self, node_id: object) -> bool:
        return isinstance(node_id, str) and node_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self):
        return iter(self._by_id)

    @property
    def node_ids(self) -> list[str]:
        """All registered node IDs, sorted for deterministic output."""
        return sorted(self._by_id.keys())

    @property
    def nodes(self) -> list[tuple[str, Node]]:
        """``(node_id, node)`` pairs sorted by ``node_id``."""
        return [(nid, self._by_id[nid]) for nid in self.node_ids]

    # ------------------------------------------------------------------
    # Hash
    # ------------------------------------------------------------------

    @property
    def registry_hash(self) -> str:
        """Stable SHA-256 of the registered node ID set.

        The hash is computed from ``sorted(node_ids)`` joined by ``\\n``.
        It changes when a node is added, removed, or renamed. Reordering the
        same set of nodes does not change the hash.

        Recorded in Checkpoints so a resume can detect an incompatible Flow
        definition (Addendum §5.4). Cross-version node-ID migration is left
        to a later version; v0.04 just stops and surfaces both hashes.
        """
        if self._hash_cache is None:
            self._hash_cache = compute_registry_hash(self.node_ids)
        return self._hash_cache

    def assert_compatible_with(self, stored_hash: str) -> None:
        """Raise ``RegistryMismatch`` if ``stored_hash`` does not match the
        current registry hash.

        Called by the resume path (P0-C) before re-entering the Flow. A
        mismatch means the Flow definition has changed since the Checkpoint
        was written; resume MUST stop (Addendum §5.4).
        """
        if stored_hash != self.registry_hash:
            raise RegistryMismatch(
                stored_hash=stored_hash,
                current_hash=self.registry_hash,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_id(node_id: str) -> None:
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("node_id must be a non-empty string")
        # Reject characters that would break trace payloads, JSON, or
        # log parsing. Allow letters, digits, ':' (for tool:file_read),
        # '_' and '-'.
        allowed = set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-"
        )
        bad = set(node_id) - allowed
        if bad:
            raise ValueError(
                f"node_id {node_id!r} contains disallowed characters: {sorted(bad)}"
            )


# ---------------------------------------------------------------------------
# Hash function (module-level so tests / artifacts can call it directly)
# ---------------------------------------------------------------------------


def compute_registry_hash(node_ids: Iterable[str]) -> str:
    """SHA-256 of the sorted ``node_ids`` joined by newlines.

    The hash is content-addressable: the same set of node IDs always
    produces the same hash regardless of insertion order. This makes it
    safe to reconstruct a registry from a Flow definition and compare
    against a Checkpoint written by a previous process.
    """
    payload = "\n".join(sorted(set(node_ids))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def serialize_registry(registry: NodeRegistry) -> str:
    """Return a JSON snapshot of the registry for artifact storage.

    The snapshot is sorted by ``node_id`` and includes the hash so a human
    can diff two snapshots without recomputing. Node object reprs are
    included for traceability but are NOT part of the hash (object repr is
    not stable across processes).
    """
    payload = {
        "schema_version": 1,
        "registry_hash": registry.registry_hash,
        "node_count": len(registry),
        "nodes": [
            {"node_id": nid, "node_type": type(node).__name__, "module": type(node).__module__}
            for nid, node in registry.nodes
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)
