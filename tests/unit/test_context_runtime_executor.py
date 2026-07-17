from __future__ import annotations

from pathlib import Path

from paperclaw.context.orchestration import ContextPolicy
from paperclaw.context.repository import SQLiteRepository
from paperclaw.harness import (
    AgentRuntimeExecutor,
    ContextOrchestratedAgentRuntimeExecutor,
    QueryEngine,
)
from tests.helpers import FakeModel, done


def test_opt_in_executor_assembles_before_each_model_call(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    model = FakeModel([done(result="assembled")])
    executor = ContextOrchestratedAgentRuntimeExecutor(
        model,
        tmp_path,
        enable_verification_gate=False,
    )
    result = QueryEngine(
        executor,
        conversation_id="conv-context-runtime",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    ).submit("return one answer")

    assert result.status == "completed"
    assert result.output == "assembled"
    assert len(executor.last_assemblies) == 1
    assembly = executor.last_assemblies[0]
    assert assembly.trace.step_id == "model-1"
    assert assembly.fingerprint
    assert "Workspace root:" in model.prompts[0]

    names = [event_type for event_type, _ in events]
    assert names.count("context.assembly.completed") == 1
    assert names.index("model.started") < names.index("context.assembly.completed")
    assert names.index("context.assembly.completed") < names.index("model.completed")
    payload = next(
        payload
        for event_type, payload in events
        if event_type == "context.assembly.completed"
    )
    assert payload["fingerprint"] == assembly.fingerprint
    assert "prompt" not in payload


def test_existing_executor_remains_parity_path(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    model = FakeModel([done(result="legacy")])
    result = QueryEngine(
        AgentRuntimeExecutor(
            model,
            tmp_path,
            enable_verification_gate=False,
        ),
        conversation_id="conv-legacy-runtime",
        event_handler=lambda event_type, payload: events.append((event_type, payload)),
    ).submit("keep old path")

    assert result.status == "completed"
    assert not any(
        event_type.startswith("context.assembly") for event_type, _ in events
    )
    assert "Workspace root:" not in model.prompts[0]


def test_assembly_trace_is_persisted_to_existing_session_events(
    tmp_path: Path,
) -> None:
    repository = SQLiteRepository(tmp_path / "context-runtime.db", migrate=True)
    try:
        executor = ContextOrchestratedAgentRuntimeExecutor(
            FakeModel([done(result="persisted")]),
            tmp_path,
            repository=repository,
            enable_verification_gate=False,
        )
        result = QueryEngine(
            executor,
            conversation_id="conv-context-persisted",
        ).submit("persist assembly trace")

        events = repository.list_events(result.run_id)
        assembly_events = [
            event
            for event in events
            if event.event_type == "context.assembly.completed"
        ]
        assert len(assembly_events) == 1
        payload = assembly_events[0].payload
        assert payload["fingerprint"] == executor.last_assemblies[0].fingerprint
        assert payload["policy_version"] == "paperclaw.context.v0.08.1"
        assert payload["query_event_sequence"] > 0
        assert "prompt" not in payload
    finally:
        repository.close()


def test_protected_overflow_maps_to_budget_exhausted(tmp_path: Path) -> None:
    policy = ContextPolicy(
        max_input_tokens=20,
        output_reserve_tokens=5,
        source_quotas=(("task", 1.0),),
    )
    executor = ContextOrchestratedAgentRuntimeExecutor(
        FakeModel([done(result="not reached")]),
        tmp_path,
        enable_verification_gate=False,
        context_policy=policy,
    )

    result = QueryEngine(
        executor,
        conversation_id="conv-context-budget",
    ).submit("A request whose generated runtime prompt cannot fit the tiny budget")

    assert result.status == "budget_exhausted"
    assert result.stop_reason == "context_budget_exhausted"
    assert result.model_calls == 1
