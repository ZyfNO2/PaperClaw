"""Addendum P0-A: stable node identity tests.

Covers:
- NodeRegistry registration, lookup, bidirectional mapping.
- IdentifiedNode Protocol runtime check.
- CompletedNode terminal behavior (stop_reason fallback, no side effects).
- compute_registry_hash stability (insertion-order independent, content-addressable).
- RegistryMismatch detection.
- serialize_registry artifact shape.
- Agent Flow integration: build_react_flow returns a NodeRegistry with the
  expected stable IDs (PF-01, PF-02).
- ID validation (disallowed characters rejected).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pocketflow import Node

from paperclaw.agent.flow import build_react_flow, default_registry
from paperclaw.models.base import ChatModel, ModelTurn
from paperclaw.runtime import (
    COMPLETED_NODE_ID,
    CompletedNode,
    IdentifiedNode,
    NodeRegistry,
    RegistryMismatch,
    compute_registry_hash,
)
from paperclaw.runtime.node_registry import serialize_registry


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeModel(ChatModel):
    """Minimal ChatModel that returns a fixed string."""

    def __init__(self, reply: str = "noop") -> None:
        self._reply = reply

    def complete(self, prompt: str) -> ModelTurn:  # noqa: D401
        return ModelTurn(content=self._reply)


class _LabeledNode(Node):
    """Node with an explicit node_id set at construction."""

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id

    def prep(self, shared):  # noqa: D401 - PocketFlow hook
        return None

    def exec(self, prep_res):  # noqa: D401 - PocketFlow hook
        return None

    def post(self, shared, prep_res, exec_res):  # noqa: D401 - PocketFlow hook
        return None


# ---------------------------------------------------------------------------
# IdentifiedNode protocol
# ---------------------------------------------------------------------------


class TestIdentifiedNodeProtocol:
    def test_node_with_class_attribute_satisfies_protocol(self):
        class _C(Node):
            node_id = "c"

            def prep(self, shared): return None
            def exec(self, prep_res): return None
            def post(self, shared, prep_res, exec_res): return None

        node = _C()
        assert isinstance(node, IdentifiedNode)

    def test_node_with_instance_attribute_satisfies_protocol(self):
        node = _LabeledNode("inst")
        assert isinstance(node, IdentifiedNode)

    def test_plain_node_does_not_satisfy_protocol(self):
        # A plain Node without node_id is NOT an IdentifiedNode.
        plain = Node()
        assert not isinstance(plain, IdentifiedNode)


# ---------------------------------------------------------------------------
# NodeRegistry basics
# ---------------------------------------------------------------------------


class TestNodeRegistryBasics:
    def test_register_and_get(self):
        reg = NodeRegistry()
        node = _LabeledNode("alpha")
        reg.register("alpha", node)
        assert reg.get("alpha") is node
        assert reg.get_id(node) == "alpha"

    def test_add_reads_node_id_attribute(self):
        reg = NodeRegistry()
        node = _LabeledNode("beta")
        node_id = reg.add(node)
        assert node_id == "beta"
        assert reg.get("beta") is node

    def test_add_many_returns_ids(self):
        reg = NodeRegistry()
        nodes = [_LabeledNode(f"n{i}") for i in range(3)]
        ids = reg.add_many(nodes)
        assert ids == ["n0", "n1", "n2"]
        assert len(reg) == 3

    def test_register_is_idempotent_for_same_pair(self):
        reg = NodeRegistry()
        node = _LabeledNode("dup")
        reg.register("dup", node)
        # Re-registering the SAME pair is a no-op.
        reg.register("dup", node)
        assert len(reg) == 1
        assert reg.get("dup") is node

    def test_register_rejects_rebind_to_different_node(self):
        reg = NodeRegistry()
        a = _LabeledNode("x")
        b = _LabeledNode("x")
        reg.register("x", a)
        with pytest.raises(ValueError, match="already registered to a different"):
            reg.register("x", b)

    def test_register_rejects_node_already_bound_to_other_id(self):
        reg = NodeRegistry()
        node = _LabeledNode("first")
        reg.register("first", node)
        with pytest.raises(ValueError, match="already registered under"):
            reg.register("second", node)

    def test_get_unknown_id_raises_keyerror(self):
        reg = NodeRegistry()
        with pytest.raises(KeyError):
            reg.get("missing")

    def test_get_id_unknown_node_raises_keyerror(self):
        reg = NodeRegistry()
        with pytest.raises(KeyError):
            reg.get_id(_LabeledNode("ghost"))

    def test_contains_and_len(self):
        reg = NodeRegistry()
        assert "x" not in reg
        reg.register("x", _LabeledNode("x"))
        assert "x" in reg
        assert len(reg) == 1

    def test_node_ids_sorted(self):
        reg = NodeRegistry()
        for nid in ("zeta", "alpha", "mid"):
            reg.register(nid, _LabeledNode(nid))
        assert reg.node_ids == ["alpha", "mid", "zeta"]

    def test_iter_yields_node_ids(self):
        reg = NodeRegistry()
        for nid in ("a", "b"):
            reg.register(nid, _LabeledNode(nid))
        assert sorted(iter(reg)) == ["a", "b"]


# ---------------------------------------------------------------------------
# ID validation
# ---------------------------------------------------------------------------


class TestNodeIdValidation:
    def test_empty_id_rejected(self):
        reg = NodeRegistry()
        with pytest.raises(ValueError, match="non-empty"):
            reg.register("", Node())

    def test_non_string_id_rejected(self):
        reg = NodeRegistry()
        with pytest.raises(ValueError):
            reg.register(123, Node())  # type: ignore[arg-type]

    def test_disallowed_characters_rejected(self):
        reg = NodeRegistry()
        # Spaces and slashes break trace payloads and JSON.
        for bad in ("has space", "has/slash", "has\nnewline", "has\"quote"):
            with pytest.raises(ValueError, match="disallowed"):
                reg.register(bad, _LabeledNode(bad))

    def test_tool_namespace_allowed(self):
        reg = NodeRegistry()
        node = _LabeledNode("tool:file_read")
        reg.register("tool:file_read", node)
        assert "tool:file_read" in reg


# ---------------------------------------------------------------------------
# Hash
# ---------------------------------------------------------------------------


class TestRegistryHash:
    def test_same_set_same_hash(self):
        ids_a = ["decide", "tool:file_read", "completed"]
        ids_b = ["completed", "decide", "tool:file_read"]  # different order
        assert compute_registry_hash(ids_a) == compute_registry_hash(ids_b)

    def test_different_set_different_hash(self):
        a = compute_registry_hash(["decide", "completed"])
        b = compute_registry_hash(["decide", "reflect"])
        assert a != b

    def test_duplicate_ids_do_not_change_hash(self):
        # set() dedups; the hash is over the SET of node IDs.
        a = compute_registry_hash(["decide", "decide", "completed"])
        b = compute_registry_hash(["decide", "completed"])
        assert a == b

    def test_registry_hash_is_cached(self):
        reg = NodeRegistry()
        reg.register("a", _LabeledNode("a"))
        first = reg.registry_hash
        # Re-read without mutation: same object identity (cached).
        assert reg.registry_hash == first

    def test_registry_hash_changes_on_mutation(self):
        reg = NodeRegistry()
        reg.register("a", _LabeledNode("a"))
        before = reg.registry_hash
        reg.register("b", _LabeledNode("b"))
        after = reg.registry_hash
        assert before != after

    def test_assert_compatible_with_passes_on_match(self):
        reg = NodeRegistry()
        reg.register("a", _LabeledNode("a"))
        reg.assert_compatible_with(reg.registry_hash)

    def test_assert_compatible_with_raises_on_mismatch(self):
        reg = NodeRegistry()
        reg.register("a", _LabeledNode("a"))
        with pytest.raises(RegistryMismatch) as exc:
            reg.assert_compatible_with("0" * 64)
        assert exc.value.stored_hash == "0" * 64
        assert exc.value.current_hash == reg.registry_hash


# ---------------------------------------------------------------------------
# CompletedNode
# ---------------------------------------------------------------------------


class TestCompletedNode:
    def test_node_id_is_completed(self):
        node = CompletedNode()
        assert node.node_id == COMPLETED_NODE_ID
        assert node.node_id == "completed"

    def test_satisfies_identified_node_protocol(self):
        assert isinstance(CompletedNode(), IdentifiedNode)

    def test_post_sets_default_stop_reason_when_none(self):
        node = CompletedNode()
        shared: dict = {}
        result = node.post(shared, None, None)
        # Returning None ends the Flow.
        assert result is None
        assert shared["stop_reason"] == "done"

    def test_post_preserves_existing_stop_reason(self):
        node = CompletedNode()
        shared = {"stop_reason": "verification_failed"}
        node.post(shared, None, None)
        # The specific reason set by an earlier node wins.
        assert shared["stop_reason"] == "verification_failed"

    def test_post_does_not_touch_shared_beyond_stop_reason(self):
        node = CompletedNode()
        shared = {"step_count": 5, "history": ["x"]}
        node.post(shared, None, None)
        # The terminal node must not mutate other shared state.
        assert shared["step_count"] == 5
        assert shared["history"] == ["x"]
        assert "stop_reason" in shared

    def test_prep_exec_return_none(self):
        # The terminal node performs no I/O.
        node = CompletedNode()
        assert node.prep({}) is None
        assert node.exec(None) is None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerializeRegistry:
    def test_serialize_returns_valid_json(self):
        reg = NodeRegistry()
        reg.register("decide", _LabeledNode("decide"))
        reg.register("completed", CompletedNode())
        text = serialize_registry(reg)
        data = json.loads(text)
        assert data["schema_version"] == 1
        assert data["node_count"] == 2
        assert data["registry_hash"] == reg.registry_hash
        ids = [n["node_id"] for n in data["nodes"]]
        assert ids == ["completed", "decide"]  # sorted

    def test_serialize_includes_node_type(self):
        reg = NodeRegistry()
        reg.register("completed", CompletedNode())
        reg.register("decide", _LabeledNode("decide"))
        data = json.loads(serialize_registry(reg))
        by_id = {n["node_id"]: n for n in data["nodes"]}
        assert by_id["completed"]["node_type"] == "CompletedNode"
        assert by_id["decide"]["node_type"] == "_LabeledNode"


# ---------------------------------------------------------------------------
# Agent Flow integration: PF-01 (stable node IDs) + PF-02 (no anonymous
# terminals)
# ---------------------------------------------------------------------------


class TestAgentFlowStableNodeIds:
    """PF-01: every runnable node and terminal has a unique stable ID.
    PF-02: no anonymous Node() terminals remain in build_react_flow.
    """

    def _build(self, enable_verification_gate: bool) -> tuple:
        model = _FakeModel()
        registry = default_registry()
        flow, node_registry = build_react_flow(
            model, registry, enable_verification_gate=enable_verification_gate
        )
        return flow, node_registry

    def test_default_flow_has_expected_node_ids(self):
        flow, reg = self._build(enable_verification_gate=False)
        ids = set(reg)
        # Always present.
        assert "decide" in ids
        assert "completed" in ids
        # One execute node per tool in default_registry.
        for tool_name in ("file_read", "file_write", "file_edit", "grep", "bash"):
            assert f"tool:{tool_name}" in ids
        # Verification gate is OFF; reflect/verify_done must NOT be present.
        assert "verify_done" not in ids
        assert "reflect" not in ids

    def test_verification_gate_flow_has_expected_node_ids(self):
        flow, reg = self._build(enable_verification_gate=True)
        ids = set(reg)
        assert "decide" in ids
        assert "verify_done" in ids
        assert "reflect" in ids
        assert "completed" in ids
        for tool_name in ("file_read", "file_write", "file_edit", "grep", "bash"):
            assert f"tool:{tool_name}" in ids

    def test_no_anonymous_node_terminals(self):
        """PF-02: no plain Node() instances in the registry. Every node must
        be an IdentifiedNode (CompletedNode or a class with node_id).
        """
        for enable_gate in (False, True):
            _flow, reg = self._build(enable_verification_gate=enable_gate)
            for node_id, node in reg.nodes:
                assert isinstance(node, IdentifiedNode), (
                    f"node {node_id!r} is not an IdentifiedNode (anonymous terminal?)"
                )

    def test_completed_node_present_in_both_gate_modes(self):
        for enable_gate in (False, True):
            _flow, reg = self._build(enable_verification_gate=enable_gate)
            assert COMPLETED_NODE_ID in reg
            completed_node = reg.get(COMPLETED_NODE_ID)
            assert isinstance(completed_node, CompletedNode)

    def test_registry_hash_is_stable_across_invocations(self):
        """Two builds of the same Flow definition produce the same hash."""
        _f1, r1 = self._build(enable_verification_gate=False)
        _f2, r2 = self._build(enable_verification_gate=False)
        assert r1.registry_hash == r2.registry_hash

    def test_registry_hash_differs_between_gate_modes(self):
        _f1, r1 = self._build(enable_verification_gate=False)
        _f2, r2 = self._build(enable_verification_gate=True)
        # Different node sets → different hash.
        assert r1.registry_hash != r2.registry_hash

    def test_build_react_flow_returns_tuple(self):
        """API contract: build_react_flow now returns (Flow, NodeRegistry).

        We check the type name rather than ``isinstance(flow, pocketflow.Flow)``
        because other tests in the same process may have re-imported
        ``pocketflow`` (e.g. the vendor integrity tests pop ``sys.modules``),
        and re-import creates a new class object that fails ``isinstance``
        even though the runtime type is correct.
        """
        result = build_react_flow(_FakeModel(), default_registry())
        assert isinstance(result, tuple)
        assert len(result) == 2
        flow, reg = result
        assert type(flow).__name__ == "Flow"
        assert type(flow).__module__.startswith("pocketflow")
        assert isinstance(reg, NodeRegistry)
