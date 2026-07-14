"""Addendum P0-B: InstrumentedFlowRunner tests.

Covers (Addendum §10 verification matrix):

- PF-03: Event order — node.started before node.completed; flow.started
  first, flow.stopped last.
- PF-04: Transition trace — action + next_node_id recorded.
- PF-05: PocketFlow parity — byte-for-byte identical shared state.
- PF-10: Retry/fallback parity — same retry count and final state.
- PF-11: Shared state is authoritative — mutations visible across nodes.
- PB1: Resume entry — starts at next_node_id, not start_node.
- PB2: None action default transition; unknown action stops flow.
- PB3+PB4: Event sequence strictly monotonic.
- PB5: Parity mode with all-None RuntimeServices.
- PB6: Error handling — node.failed emitted with stable error code, then
  re-raised. Phase-specific codes (prep/exec/post).
- Cancellation: flow.stopped with stop_reason="cancelled".
"""

from __future__ import annotations

import copy
import warnings
from typing import Any

import pytest
from pocketflow import Flow, Node

from paperclaw.runtime import (
    NODE_EXEC_FAILED,
    NODE_POST_FAILED,
    NODE_PREP_FAILED,
    RESUME_REGISTRY_MISMATCH,
    CompletedNode,
    FlowResumePoint,
    InMemoryCheckpointWriter,
    InstrumentedFlowRunner,
    NodeIdentityMissingError,
    NodeRegistry,
    ResumeRegistryMismatchError,
    RuntimeServices,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class RecordingSink:
    """EventSink that records every emit call with a monotonic sequence.

    Mimics the SessionService.emit contract: returns a strictly increasing
    sequence number so the runner can track ``last_committed_sequence``.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._seq = 0

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        agent_id: str = "",
        task_id: str | None = None,
    ) -> int:
        self._seq += 1
        # Store a deep copy so later mutations don't affect recorded events.
        self.events.append({
            "event_type": event_type,
            "payload": copy.deepcopy(payload),
            "sequence": self._seq,
        })
        return self._seq

    @property
    def event_types(self) -> list[str]:
        return [e["event_type"] for e in self.events]

    def payloads_for(self, event_type: str) -> list[dict[str, Any]]:
        return [e["payload"] for e in self.events if e["event_type"] == event_type]


class CancellationToken:
    """Simple cooperative cancellation token with ``is_cancelled`` bool.

    The runner's preferred API (Addendum §4 — documented in flow_runner.py).
    """

    def __init__(self) -> None:
        self.is_cancelled = False

    def cancel(self) -> None:
        self.is_cancelled = True


class TraceNode(Node):
    """Node that appends its ``node_id`` to ``shared["trace"]`` and returns
    a fixed action. Used to verify execution order and shared-state
    visibility (PF-11).
    """

    def __init__(self, node_id: str, action: str | None = "default") -> None:
        super().__init__()
        self.node_id = node_id
        self._action = action

    def prep(self, shared: dict) -> Any:
        shared.setdefault("trace", []).append(self.node_id)
        return None

    def exec(self, prep_res: Any) -> Any:
        return None

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        return self._action


class FlakyNode(Node):
    """Node that fails ``fail_count`` times then succeeds. Used for PF-10
    retry parity. Tracks attempts on the instance so both native and
    instrumented runs can verify the retry count.
    """

    node_id = "flaky"

    def __init__(self, fail_count: int, max_retries: int = 3) -> None:
        super().__init__(max_retries=max_retries, wait=0)
        self._fail_count = fail_count
        self._attempts = 0

    def prep(self, shared: dict) -> Any:
        return None

    def exec(self, prep_res: Any) -> str:
        self._attempts += 1
        if self._attempts <= self._fail_count:
            raise ValueError(f"fail {self._attempts}")
        return "ok"

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        shared["result"] = exec_res
        shared["attempts"] = self._attempts
        return None


class FallbackNode(Node):
    """Node that always fails ``exec`` and returns a default from
    ``exec_fallback``. Used for PF-10 fallback parity.
    """

    node_id = "fallback"

    def __init__(self, max_retries: int = 2) -> None:
        super().__init__(max_retries=max_retries, wait=0)

    def prep(self, shared: dict) -> Any:
        return None

    def exec(self, prep_res: Any) -> str:
        raise ValueError("always fails")

    def exec_fallback(self, prep_res: Any, exc: BaseException) -> str:
        return "fallback_result"

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        shared["result"] = exec_res
        return None


class PrepFailNode(Node):
    """Node whose ``prep`` raises. Used for PB6 phase-specific error codes."""

    node_id = "prep_fail"

    def prep(self, shared: dict) -> Any:
        raise ValueError("prep failed")

    def exec(self, prep_res: Any) -> Any:
        return None

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        return None


class ExecFailNode(Node):
    """Node whose ``exec`` raises. Used for PB6 NODE_EXEC_FAILED."""

    node_id = "exec_fail"

    def prep(self, shared: dict) -> Any:
        return None

    def exec(self, prep_res: Any) -> Any:
        raise ValueError("exec failed")

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        return None


class PostFailNode(Node):
    """Node whose ``post`` raises. Used for PB6 NODE_POST_FAILED."""

    node_id = "post_fail"

    def prep(self, shared: dict) -> Any:
        return None

    def exec(self, prep_res: Any) -> Any:
        return None

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        raise ValueError("post failed")


class CancellingNode(Node):
    """Node that cancels the token during ``exec``. Used for cancellation
    tests — the runner should detect cancellation before the NEXT node and
    emit ``flow.stopped`` with ``stop_reason="cancelled"``.
    """

    node_id = "cancelling"

    def __init__(self, token: CancellationToken) -> None:
        super().__init__()
        self._token = token

    def prep(self, shared: dict) -> Any:
        shared.setdefault("trace", []).append(self.node_id)
        return None

    def exec(self, prep_res: Any) -> Any:
        self._token.cancel()
        return None

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str | None:
        return "default"


# ---------------------------------------------------------------------------
# Flow builders for tests
# ---------------------------------------------------------------------------


def _build_linear_flow(node_ids: list[str], actions: list[str | None] | None = None) -> tuple[Flow, NodeRegistry]:
    """Build a linear flow A → B → C → ... with a NodeRegistry.

    Each node is a ``TraceNode`` that appends its id to ``shared["trace"]``.
    The last node has no successors (terminal). ``actions`` controls the
    ``post`` return value of each node; default is ``"default"`` for all
    but the last (which returns ``None``).
    """
    if actions is None:
        actions = ["default"] * (len(node_ids) - 1) + [None]
    assert len(actions) == len(node_ids)

    nodes = [TraceNode(nid, act) for nid, act in zip(node_ids, actions)]
    for i in range(len(nodes) - 1):
        nodes[i] - "default" >> nodes[i + 1]
    flow = Flow(start=nodes[0])

    registry = NodeRegistry()
    for n in nodes:
        registry.add(n)
    return flow, registry


# ---------------------------------------------------------------------------
# PF-03: Event order
# ---------------------------------------------------------------------------


class TestEventOrder:
    """PF-03: node.started sequence < node.completed sequence for each node;
    flow.started is first, flow.stopped is last."""

    def test_event_order_node_started_before_completed(self):
        flow, registry = _build_linear_flow(["a", "b", "c"])
        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)

        runner = InstrumentedFlowRunner()
        shared: dict = {}
        runner.run(flow, shared, services=services)

        types = sink.event_types
        # flow.started is first, flow.stopped is last.
        assert types[0] == "flow.started"
        assert types[-1] == "flow.stopped"

        # For each node, node.started sequence < node.completed sequence.
        started_seqs = {e["payload"]["node_id"]: e["sequence"]
                        for e in sink.events if e["event_type"] == "node.started"}
        completed_seqs = {e["payload"]["node_id"]: e["sequence"]
                          for e in sink.events if e["event_type"] == "node.completed"}
        assert set(started_seqs.keys()) == {"a", "b", "c"}
        assert set(completed_seqs.keys()) == {"a", "b", "c"}
        for nid in ("a", "b", "c"):
            assert started_seqs[nid] < completed_seqs[nid], (
                f"node.started for {nid} must come before node.completed"
            )

    def test_all_seven_event_types_present(self):
        """The run emits all 7 event types (no checkpoint writer → no
        checkpoint.committed unless writer is set)."""
        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)

        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        types = set(sink.event_types)
        # Without a checkpoint_writer, checkpoint.committed is NOT emitted.
        assert "flow.started" in types
        assert "node.started" in types
        assert "node.completed" in types
        assert "transition.selected" in types
        assert "flow.stopped" in types

    def test_checkpoint_committed_emitted_when_writer_present(self):
        flow, registry = _build_linear_flow(["a", "b"])
        sink = RecordingSink()
        # P0-C: the writer is now a CheckpointWriter Protocol object, not a
        # bare callable. InMemoryCheckpointWriter records the Checkpoint
        # objects so the test can assert on their fields.
        writer = InMemoryCheckpointWriter()
        services = RuntimeServices(
            event_sink=sink,
            node_registry=registry,
            checkpoint_writer=writer,
        )
        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        types = set(sink.event_types)
        assert "checkpoint.committed" in types
        assert len(writer.committed) == 2  # one per node
        # Each committed Checkpoint records the node identity triple.
        assert writer.committed[0].completed_node_id == "a"
        assert writer.committed[0].next_node_id == "b"
        assert writer.committed[1].completed_node_id == "b"


# ---------------------------------------------------------------------------
# PF-04: Transition trace
# ---------------------------------------------------------------------------


class TestTransitionTrace:
    """PF-04: each transition.selected event records from_node_id, action,
    and to_node_id correctly."""

    def test_transition_selected_records_action_and_next_node(self):
        # Build a 3-node flow with named actions.
        a = TraceNode("a", action="go")
        b = TraceNode("b", action="next")
        c = TraceNode("c", action="done")
        a - "go" >> b
        b - "next" >> c
        # c has no successors → terminal.

        registry = NodeRegistry()
        registry.add(a)
        registry.add(b)
        registry.add(c)

        flow = Flow(start=a)
        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)

        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        transitions = sink.payloads_for("transition.selected")
        assert len(transitions) == 3

        # a → b via "go"
        assert transitions[0]["from_node_id"] == "a"
        assert transitions[0]["action"] == "go"
        assert transitions[0]["to_node_id"] == "b"

        # b → c via "next"
        assert transitions[1]["from_node_id"] == "b"
        assert transitions[1]["action"] == "next"
        assert transitions[1]["to_node_id"] == "c"

        # c → None (terminal, action "done" has no successor)
        assert transitions[2]["from_node_id"] == "c"
        assert transitions[2]["action"] == "done"
        assert transitions[2]["to_node_id"] is None


# ---------------------------------------------------------------------------
# PF-05 + PB5: PocketFlow parity
# ---------------------------------------------------------------------------


class TestParity:
    """PF-05: byte-for-byte identical shared state vs native Flow.run.
    PB5: parity mode activates when all services are None."""

    def test_instrumented_flow_parity(self):
        """Build a flow, run natively and via runner, assert shared equality."""
        for seed in range(5):
            a = TraceNode(f"a{seed}", action="go")
            b = TraceNode(f"b{seed}", action="go")
            c = TraceNode(f"c{seed}", action="done")
            a - "go" >> b
            b - "go" >> c
            flow = Flow(start=a)

            # Native run.
            shared_native: dict = {}
            flow.run(shared_native)

            # Instrumented run (parity mode — all services None).
            shared_inst: dict = {}
            runner = InstrumentedFlowRunner()
            runner.run(flow, shared_inst, services=RuntimeServices())

            assert shared_native == shared_inst, (
                f"parity broken at seed {seed}: "
                f"native={shared_native} instrumented={shared_inst}"
            )

    def test_parity_mode_with_no_services(self):
        """RuntimeServices() with all defaults → same result as native."""
        a = TraceNode("x", action="default")
        b = TraceNode("y", action=None)
        a - "default" >> b
        flow = Flow(start=a)

        shared_native: dict = {}
        flow.run(shared_native)

        shared_inst: dict = {}
        runner = InstrumentedFlowRunner()
        runner.run(flow, shared_inst, services=RuntimeServices())

        assert shared_native == shared_inst

    def test_parity_returns_same_action(self):
        """The runner returns the same last_action as native Flow.run."""
        a = TraceNode("a", action="final_action")
        flow = Flow(start=a)

        shared_native: dict = {}
        ret_native = flow.run(shared_native)

        shared_inst: dict = {}
        runner = InstrumentedFlowRunner()
        ret_inst = runner.run(flow, shared_inst, services=RuntimeServices())

        assert ret_native == ret_inst


# ---------------------------------------------------------------------------
# PF-10: Retry and fallback parity
# ---------------------------------------------------------------------------


class TestRetryParity:
    """PF-10: retry/fallback semantics identical to native PocketFlow."""

    def test_retry_then_success_parity(self):
        """A node that fails N-1 times then succeeds. Both runners retry the
        same number of times with the same final shared state."""
        # Native run.
        native_node = FlakyNode(fail_count=2, max_retries=3)
        native_flow = Flow(start=native_node)
        shared_native: dict = {}
        native_flow.run(shared_native)

        # Instrumented run (parity mode).
        inst_node = FlakyNode(fail_count=2, max_retries=3)
        inst_flow = Flow(start=inst_node)
        shared_inst: dict = {}
        runner = InstrumentedFlowRunner()
        runner.run(inst_flow, shared_inst, services=RuntimeServices())

        assert shared_native == shared_inst
        assert shared_native["attempts"] == 3
        assert shared_native["result"] == "ok"

    def test_retry_fallback_parity(self):
        """A node whose exec_fallback returns a default. Both runners
        produce the same shared state."""
        # Native run.
        native_node = FallbackNode(max_retries=2)
        native_flow = Flow(start=native_node)
        shared_native: dict = {}
        native_flow.run(shared_native)

        # Instrumented run (parity mode).
        inst_node = FallbackNode(max_retries=2)
        inst_flow = Flow(start=inst_node)
        shared_inst: dict = {}
        runner = InstrumentedFlowRunner()
        runner.run(inst_flow, shared_inst, services=RuntimeServices())

        assert shared_native == shared_inst
        assert shared_native["result"] == "fallback_result"


# ---------------------------------------------------------------------------
# PF-11: Shared state is authoritative
# ---------------------------------------------------------------------------


class TestSharedAuthoritative:
    """PF-11: shared mutations by node prep/exec/post are visible to
    subsequent nodes (no copy of shared state)."""

    def test_shared_state_is_authoritative(self):
        """Node A writes to shared["value"]; Node B reads it. If shared were
        copied, B would see an empty dict."""
        class ProducerNode(Node):
            node_id = "producer"

            def prep(self, shared):
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                shared["value"] = 42
                return "default"

        class ConsumerNode(Node):
            node_id = "consumer"

            def prep(self, shared):
                # Read what ProducerNode wrote. If shared were copied, this
                # would raise KeyError.
                self._seen = shared.get("value")
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                shared["consumed"] = self._seen
                return None

        producer = ProducerNode()
        consumer = ConsumerNode()
        producer - "default" >> consumer
        flow = Flow(start=producer)

        registry = NodeRegistry()
        registry.add(producer)
        registry.add(consumer)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()
        shared: dict = {}
        runner.run(flow, shared, services=services)

        assert shared["value"] == 42
        assert shared["consumed"] == 42


# ---------------------------------------------------------------------------
# PB3+PB4: Event sequence strictly monotonic
# ---------------------------------------------------------------------------


class TestEventSequence:
    """PB3+PB4: sequences returned by the sink are strictly increasing."""

    def test_event_sequence_strictly_monotonic(self):
        flow, registry = _build_linear_flow(["a", "b", "c"])
        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)

        runner = InstrumentedFlowRunner()
        runner.run(flow, {}, services=services)

        sequences = [e["sequence"] for e in sink.events]
        assert sequences == sorted(sequences), "sequences must be monotonic"
        assert len(sequences) == len(set(sequences)), "sequences must be unique"


# ---------------------------------------------------------------------------
# PB6: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """PB6: node.failed emitted with stable error code, then re-raised.
    Phase-specific codes (prep/exec/post)."""

    def test_node_failure_emits_node_failed_and_reraises(self):
        """exec raises ValueError; runner emits node.failed with
        error_type="ValueError" and error_code="NODE_EXEC_FAILED", then
        re-raises."""
        node = ExecFailNode()
        flow = Flow(start=node)
        registry = NodeRegistry()
        registry.add(node)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()

        with pytest.raises(ValueError, match="exec failed"):
            runner.run(flow, {}, services=services)

        failed = sink.payloads_for("node.failed")
        assert len(failed) == 1
        assert failed[0]["node_id"] == "exec_fail"
        assert failed[0]["error_type"] == "ValueError"
        assert failed[0]["error_code"] == NODE_EXEC_FAILED

    def test_prep_failure_classified_as_prep_failed(self):
        """prep raises; assert error_code == NODE_PREP_FAILED."""
        node = PrepFailNode()
        flow = Flow(start=node)
        registry = NodeRegistry()
        registry.add(node)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()

        with pytest.raises(ValueError, match="prep failed"):
            runner.run(flow, {}, services=services)

        failed = sink.payloads_for("node.failed")
        assert len(failed) == 1
        assert failed[0]["error_code"] == NODE_PREP_FAILED

    def test_post_failure_classified_as_post_failed(self):
        """post raises; assert error_code == NODE_POST_FAILED."""
        node = PostFailNode()
        flow = Flow(start=node)
        registry = NodeRegistry()
        registry.add(node)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()

        with pytest.raises(ValueError, match="post failed"):
            runner.run(flow, {}, services=services)

        failed = sink.payloads_for("node.failed")
        assert len(failed) == 1
        assert failed[0]["error_code"] == NODE_POST_FAILED

    def test_flow_stopped_not_emitted_on_crash(self):
        """When a node raises, flow.stopped is NOT emitted — the exception
        propagates and the caller handles terminal state."""
        node = ExecFailNode()
        flow = Flow(start=node)
        registry = NodeRegistry()
        registry.add(node)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()

        with pytest.raises(ValueError):
            runner.run(flow, {}, services=services)

        assert "flow.stopped" not in sink.event_types


# ---------------------------------------------------------------------------
# PB2: Transition semantics
# ---------------------------------------------------------------------------


class TestTransitionSemantics:
    """PB2: None action uses default transition; unknown action stops flow."""

    def test_none_action_uses_default_transition(self):
        """post returns None; runner follows default edge like PocketFlow."""
        a = TraceNode("a", action=None)  # None → default transition
        b = TraceNode("b", action="done")
        a - "default" >> b  # default edge
        flow = Flow(start=a)

        registry = NodeRegistry()
        registry.add(a)
        registry.add(b)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()
        shared: dict = {}
        runner.run(flow, shared, services=services)

        # Both nodes executed.
        assert shared["trace"] == ["a", "b"]

        # transition.selected for a has action=None, to_node_id="b".
        transitions = sink.payloads_for("transition.selected")
        assert transitions[0]["from_node_id"] == "a"
        assert transitions[0]["action"] is None
        assert transitions[0]["to_node_id"] == "b"

    def test_unknown_action_stops_flow_cleanly(self):
        """post returns "unknown_action"; runner emits flow.stopped and
        exits (matching PocketFlow behavior — warns and ends)."""
        a = TraceNode("a", action="unknown_action")
        b = TraceNode("b", action="done")
        a - "default" >> b  # only default edge; "unknown_action" not registered
        flow = Flow(start=a)

        registry = NodeRegistry()
        registry.add(a)
        registry.add(b)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()

        # PocketFlow warns on unknown action; suppress the warning.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            shared: dict = {}
            runner.run(flow, shared, services=services)

        # Only node a executed; b was NOT reached.
        assert shared["trace"] == ["a"]

        # flow.stopped was emitted.
        assert "flow.stopped" in sink.event_types

        # transition.selected for a has to_node_id=None (no successor for
        # "unknown_action").
        transitions = sink.payloads_for("transition.selected")
        assert transitions[0]["from_node_id"] == "a"
        assert transitions[0]["action"] == "unknown_action"
        assert transitions[0]["to_node_id"] is None


# ---------------------------------------------------------------------------
# PB1: Resume entry
# ---------------------------------------------------------------------------


class TestResume:
    """PB1: resume enters at next_node_id, not flow.start_node. Resume
    without registry raises RESUME_REGISTRY_MISMATCH."""

    def test_resume_enters_at_next_node_id(self):
        """Provide resume_point.next_node_id; runner starts there, not at
        flow.start_node. The completed node is NOT re-executed."""
        a = TraceNode("a", action="default")
        b = TraceNode("b", action="default")
        c = TraceNode("c", action="done")
        a - "default" >> b
        b - "default" >> c
        flow = Flow(start=a)

        registry = NodeRegistry()
        registry.add(a)
        registry.add(b)
        registry.add(c)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()

        resume_point = FlowResumePoint(
            run_id="run-resume-test",
            completed_node_id="a",
            last_action="default",
            next_node_id="b",
            last_committed_sequence=5,
            state_revision=1,
        )
        shared: dict = {}
        runner.run(flow, shared, services=services, resume_point=resume_point)

        # a was NOT re-executed; only b and c.
        assert shared["trace"] == ["b", "c"]

        # flow.started records resume_from.
        started = sink.payloads_for("flow.started")
        assert started[0]["start_node_id"] == "b"
        assert started[0]["resume_from"] == "a"

    def test_resume_without_registry_raises(self):
        """resume_point given but services.node_registry is None → raises
        with stable error code RESUME_REGISTRY_MISMATCH."""
        a = TraceNode("a", action="done")
        flow = Flow(start=a)

        # No registry, no sink — just a resume_point.
        services = RuntimeServices()
        runner = InstrumentedFlowRunner()

        resume_point = FlowResumePoint(
            run_id="run-test",
            completed_node_id=None,
            last_action=None,
            next_node_id="a",
            last_committed_sequence=0,
            state_revision=0,
        )

        with pytest.raises(ResumeRegistryMismatchError) as exc_info:
            runner.run(flow, {}, services=services, resume_point=resume_point)

        assert exc_info.value.error_code == RESUME_REGISTRY_MISMATCH

    def test_resume_with_unknown_node_id_raises(self):
        """resume_point.next_node_id not in registry → raises
        ResumeRegistryMismatchError."""
        a = TraceNode("a", action="done")
        flow = Flow(start=a)

        registry = NodeRegistry()
        registry.add(a)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()

        resume_point = FlowResumePoint(
            run_id="run-test",
            completed_node_id=None,
            last_action=None,
            next_node_id="nonexistent",
            last_committed_sequence=0,
            state_revision=0,
        )

        with pytest.raises(ResumeRegistryMismatchError) as exc_info:
            runner.run(flow, {}, services=services, resume_point=resume_point)

        assert exc_info.value.error_code == RESUME_REGISTRY_MISMATCH


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestCancellation:
    """Cancellation: token with is_cancelled=True set after first node;
    runner emits flow.stopped with stop_reason="cancelled" and does not
    execute subsequent nodes."""

    def test_cancellation_between_nodes_emits_flow_stopped(self):
        """Node A cancels the token during exec. The runner checks the token
        before node B and stops. B and C are NOT executed."""
        token = CancellationToken()
        a = CancellingNode(token)
        b = TraceNode("b", action="default")
        c = TraceNode("c", action="done")
        a - "default" >> b
        b - "default" >> c
        flow = Flow(start=a)

        registry = NodeRegistry()
        registry.add(a)
        registry.add(b)
        registry.add(c)

        sink = RecordingSink()
        services = RuntimeServices(
            event_sink=sink,
            node_registry=registry,
            cancellation_token=token,
        )
        runner = InstrumentedFlowRunner()
        shared: dict = {}
        runner.run(flow, shared, services=services)

        # Only the cancelling node executed; b and c were NOT reached.
        assert shared["trace"] == ["cancelling"]

        # flow.stopped emitted with stop_reason="cancelled".
        stopped = sink.payloads_for("flow.stopped")
        assert len(stopped) == 1
        assert stopped[0]["stop_reason"] == "cancelled"
        assert stopped[0]["last_node_id"] == "cancelling"

        # node.started for the cancelling node exists, but NOT for b.
        started_nodes = [e["payload"]["node_id"]
                         for e in sink.events if e["event_type"] == "node.started"]
        assert "cancelling" in started_nodes
        assert "b" not in started_nodes

    def test_cancellation_before_first_node(self):
        """Token already cancelled before the run → no nodes execute,
        flow.stopped emitted with step_count=0."""
        token = CancellationToken()
        token.cancel()

        a = TraceNode("a", action="done")
        flow = Flow(start=a)

        registry = NodeRegistry()
        registry.add(a)

        sink = RecordingSink()
        services = RuntimeServices(
            event_sink=sink,
            node_registry=registry,
            cancellation_token=token,
        )
        runner = InstrumentedFlowRunner()
        shared: dict = {}
        runner.run(flow, shared, services=services)

        # No nodes executed.
        assert "trace" not in shared

        stopped = sink.payloads_for("flow.stopped")
        assert stopped[0]["stop_reason"] == "cancelled"
        assert stopped[0]["step_count"] == 0


# ---------------------------------------------------------------------------
# CompletedNode integration
# ---------------------------------------------------------------------------


class TestCompletedNodeIntegration:
    """Verify the runner works with PaperClaw's CompletedNode terminal."""

    def test_completed_node_sets_stop_reason_done(self):
        a = TraceNode("a", action="done")
        completed = CompletedNode()
        a - "done" >> completed
        flow = Flow(start=a)

        registry = NodeRegistry()
        registry.add(a)
        registry.add(completed)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()
        shared: dict = {}
        runner.run(flow, shared, services=services)

        # CompletedNode.post sets stop_reason to "done".
        assert shared.get("stop_reason") == "done"

        # flow.stopped uses shared["stop_reason"].
        stopped = sink.payloads_for("flow.stopped")
        assert stopped[0]["stop_reason"] == "done"
        assert stopped[0]["last_node_id"] == "completed"

    def test_completed_node_preserves_existing_stop_reason(self):
        a = TraceNode("a", action="done")
        completed = CompletedNode()
        a - "done" >> completed
        flow = Flow(start=a)

        registry = NodeRegistry()
        registry.add(a)
        registry.add(completed)

        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=registry)
        runner = InstrumentedFlowRunner()
        shared = {"stop_reason": "verification_failed"}
        runner.run(flow, shared, services=services)

        # Existing stop_reason is preserved by CompletedNode.post.
        assert shared["stop_reason"] == "verification_failed"
        stopped = sink.payloads_for("flow.stopped")
        assert stopped[0]["stop_reason"] == "verification_failed"


# ---------------------------------------------------------------------------
# Node identity missing (defensive)
# ---------------------------------------------------------------------------


class TestNodeIdentityMissing:
    """Defensive: a node without node_id and not in registry raises
    NodeIdentityMissingError."""

    def test_anonymous_node_raises_identity_missing(self):
        """A plain Node() without node_id and not in registry → raises
        NodeIdentityMissingError with stable error code."""
        # Use a plain Node with no node_id and no registry.
        plain = Node()
        flow = Flow(start=plain)

        # event_sink is set so we go through the instrumented path.
        # No registry → _resolve_node_id cannot find node_id.
        sink = RecordingSink()
        services = RuntimeServices(event_sink=sink, node_registry=None)
        runner = InstrumentedFlowRunner()

        with pytest.raises(NodeIdentityMissingError) as exc_info:
            runner.run(flow, {}, services=services)

        assert exc_info.value.error_code == "NODE_IDENTITY_MISSING"
