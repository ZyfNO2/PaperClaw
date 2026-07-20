from __future__ import annotations

import threading
from pathlib import Path

import pytest

from paperclaw.message_bus import SQLiteMessageBusStore
from paperclaw.multiagent.bus_runtime import (
    TEAM_DLQ_TOPIC,
    TEAM_EVENT_TOPIC,
    TEAM_REQUEST_TOPIC,
    TeamRunRequest,
)
from paperclaw.multiagent.contracts import AgentTask, TeamBudget, TeamStopReason
from paperclaw.multiagent.coordinator import CoordinatorResult
from paperclaw.multiagent.resilient_runtime import (
    FailureDisposition,
    InjectedCrash,
    ResilientBusDrivenTeamRuntime,
    SQLiteResilientChoreographyStore,
    TEAM_CANCEL_TOPIC,
    TeamCancellationRequest,
)


class CompletingCoordinator:
    def __init__(self):
        self.run_count = 0
        self.cancelled: list[str] = []

    def run(self, user_goal, tasks):
        self.run_count += 1
        return CoordinatorResult(
            stop_reason=TeamStopReason.ALL_TASKS_COMPLETED,
            summary="complete",
        )

    def cancel(self, task_id, tasks):
        self.cancelled.append(task_id)


class BlockingCoordinator:
    def __init__(self):
        self.started = threading.Event()
        self.cancel_event = threading.Event()
        self.cancelled: list[str] = []

    def run(self, user_goal, tasks):
        self.started.set()
        if not self.cancel_event.wait(timeout=3):
            raise TimeoutError("cancellation was not delivered")
        return CoordinatorResult(
            stop_reason=TeamStopReason.CANCELLED,
            summary="cancelled",
        )

    def cancel(self, task_id, tasks):
        self.cancelled.append(task_id)
        self.cancel_event.set()


class CrashOnce:
    def __init__(self, target: str):
        self.target = target
        self.fired = False

    def __call__(self, checkpoint, context):
        if checkpoint == self.target and not self.fired:
            self.fired = True
            raise InjectedCrash(checkpoint)


def make_request(request_id: str = "resilient-1") -> TeamRunRequest:
    return TeamRunRequest(
        request_id=request_id,
        user_goal="complete a resilient check",
        tasks=(
            AgentTask(
                task_id="check",
                title="check",
                objective="complete check",
                acceptance_criteria=["complete"],
                allowed_paths=["."],
                allowed_tools=[],
                max_steps=2,
            ),
        ),
        budget=TeamBudget(
            max_agents=1,
            max_total_steps=2,
            max_total_model_calls=2,
            max_fix_rounds=0,
        ),
    )


def build_runtime(
    tmp_path: Path,
    coordinator_factory,
    *,
    fault_injector=None,
    max_attempts=3,
):
    bus = SQLiteMessageBusStore(tmp_path / "bus.sqlite3")
    store = SQLiteResilientChoreographyStore(tmp_path / "state.sqlite3")
    runtime = ResilientBusDrivenTeamRuntime(
        bus,
        store,
        coordinator_factory,
        fault_injector=fault_injector,
        max_attempts=max_attempts,
        cancellation_poll_seconds=0.005,
    )
    return bus, store, runtime


def event_types(bus):
    return [
        message.payload.get("event_type")
        for message in bus.pull("audit", TEAM_EVENT_TOPIC, limit=1000)
    ]


def test_restart_flushes_terminal_outbox_before_ack_without_reexecution(tmp_path: Path):
    coordinator = CompletingCoordinator()
    bus, store, runtime = build_runtime(
        tmp_path,
        lambda *_args: coordinator,
        fault_injector=CrashOnce("after_terminal_committed"),
    )
    message = runtime.submit(make_request("after-commit"))

    with pytest.raises(InjectedCrash):
        runtime.run_once()

    state = store.get_attempt(runtime.consumer_id, message.message_id)
    assert state is not None and state.terminal is True
    assert len(store.pending_outbox(runtime.consumer_id, message.message_id)) == 2
    assert bus.get_cursor(runtime.consumer_id, TEAM_REQUEST_TOPIC).ack_sequence == 0
    assert coordinator.run_count == 1

    _, _, restarted = build_runtime(
        tmp_path,
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("terminal request must not re-execute")
        ),
    )
    outcome = restarted.run_once()[0]

    assert outcome.terminal is True
    assert outcome.acknowledged is True
    assert coordinator.run_count == 1
    assert bus.get_cursor(runtime.consumer_id, TEAM_REQUEST_TOPIC).ack_sequence == message.sequence
    assert event_types(bus).count("team.run.metrics") == 1
    assert event_types(bus).count("team.run.terminal") == 1


def test_publish_before_delivered_mark_is_exactly_idempotent_on_restart(tmp_path: Path):
    coordinator = CompletingCoordinator()
    bus, store, runtime = build_runtime(
        tmp_path,
        lambda *_args: coordinator,
        fault_injector=CrashOnce("after_outbox_published"),
    )
    message = runtime.submit(make_request("publish-window"))

    with pytest.raises(InjectedCrash):
        runtime.run_once()

    assert len(store.pending_outbox(runtime.consumer_id, message.message_id)) == 2
    assert event_types(bus).count("team.run.metrics") == 1

    _, _, restarted = build_runtime(tmp_path, lambda *_args: coordinator)
    outcome = restarted.run_once()[0]

    assert outcome.acknowledged is True
    assert coordinator.run_count == 1
    assert event_types(bus).count("team.run.metrics") == 1
    assert event_types(bus).count("team.run.terminal") == 1


def test_ack_crash_window_recovers_without_republishing_or_reexecution(tmp_path: Path):
    coordinator = CompletingCoordinator()
    bus, store, runtime = build_runtime(
        tmp_path,
        lambda *_args: coordinator,
        fault_injector=CrashOnce("before_request_ack"),
    )
    message = runtime.submit(make_request("ack-window"))

    with pytest.raises(InjectedCrash):
        runtime.run_once()

    assert store.all_outbox_delivered(runtime.consumer_id, message.message_id) is True
    before = event_types(bus)
    assert before.count("team.run.metrics") == 1
    assert before.count("team.run.terminal") == 1

    _, _, restarted = build_runtime(tmp_path, lambda *_args: coordinator)
    outcome = restarted.run_once()[0]

    assert outcome.acknowledged is True
    assert coordinator.run_count == 1
    assert event_types(bus) == before


def test_permanent_failure_dead_letters_and_acks_without_retry(tmp_path: Path):
    bus, store, runtime = build_runtime(
        tmp_path,
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid provider config")),
        max_attempts=5,
    )
    message = runtime.submit(make_request("permanent-failure"))

    outcome = runtime.run_once()[0]

    assert outcome.terminal is True
    assert outcome.dead_lettered is True
    assert outcome.acknowledged is True
    assert outcome.attempt == 1
    assert outcome.metrics["failure_disposition"] == FailureDisposition.PERMANENT.value
    assert bus.get_cursor(runtime.consumer_id, TEAM_REQUEST_TOPIC).ack_sequence == message.sequence
    dlq = bus.pull("operator", TEAM_DLQ_TOPIC)
    assert len(dlq) == 1
    assert dlq[0].payload["failure_disposition"] == "permanent"


def test_retryable_timeout_reexecutes_then_terminalizes(tmp_path: Path):
    coordinator = CompletingCoordinator()
    calls = 0

    def factory(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("provider timeout")
        return coordinator

    bus, _, runtime = build_runtime(tmp_path, factory, max_attempts=3)
    message = runtime.submit(make_request("retry-success"))

    first = runtime.run_once()[0]
    assert first.terminal is False
    assert first.acknowledged is False
    assert first.metrics["failure_disposition"] == "retryable"

    second = runtime.run_once()[0]
    assert second.terminal is True
    assert second.acknowledged is True
    assert second.attempt == 2
    assert calls == 2
    assert coordinator.run_count == 1
    assert bus.get_cursor(runtime.consumer_id, TEAM_REQUEST_TOPIC).ack_sequence == message.sequence
    assert "team.run.retry_scheduled" in event_types(bus)


def test_bus_cancellation_calls_existing_coordinator_cancel_and_acks(tmp_path: Path):
    coordinator = BlockingCoordinator()
    bus, _, runtime = build_runtime(tmp_path, lambda *_args: coordinator)
    request = make_request("cancel-active")
    request_message = runtime.submit(request)
    cancellation_message = runtime.submit_cancellation(
        TeamCancellationRequest(
            cancellation_id="cancel-active-1",
            request_id=request.request_id,
            task_ids=("check",),
            reason="operator stop",
        )
    )

    outcome = runtime.run_once()[0]

    assert outcome.terminal is True
    assert outcome.acknowledged is True
    assert coordinator.cancelled == ["check"]
    assert bus.get_cursor(runtime.consumer_id, TEAM_REQUEST_TOPIC).ack_sequence == request_message.sequence
    cancel_consumer = cancellation_message.recipient_id
    assert cancel_consumer is not None
    assert bus.get_cursor(cancel_consumer, TEAM_CANCEL_TOPIC).ack_sequence == cancellation_message.sequence
    assert "team.cancel.accepted" in event_types(bus)
