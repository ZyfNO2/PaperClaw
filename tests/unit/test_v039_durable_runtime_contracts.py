"""Contract tests for the v0.39 durable runtime hardening slice."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from paperclaw.context.migrations import MIGRATIONS, MigrationRunner, open_connection
from paperclaw.context.orchestration import (
    ContextOrchestrator,
    ContextPolicy,
    ContextRequest,
)
from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.harness import ContextOrchestratedAgentRuntimeExecutor, QueryEngine
from paperclaw.memory.contracts import MemorySourceRef
from paperclaw.memory.service import MemoryService
from paperclaw.memory.store import FileMemoryStore
from paperclaw.session_commands import SessionOperator
from tests.helpers import FakeModel, done


@pytest.fixture
def repo(tmp_path: Path) -> SQLiteRepository:
    repository = SQLiteRepository(tmp_path / "runtime.db", migrate=True)
    yield repository
    repository.close()


def test_session_event_idempotency_key_is_durable_and_concurrent_safe(
    repo: SQLiteRepository,
    tmp_path: Path,
) -> None:
    repo.create_conversation("session-1")
    repo.start_run("run-1", "session-1", "agent", "agent")

    repo2 = SQLiteRepository(tmp_path / "runtime.db", migrate=True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(
                repo.append_event_with_auto_sequence,
                event_id="event-1",
                idempotency_key="model-call-1",
                conversation_id="session-1",
                run_id="run-1",
                event_type="model.started",
                payload={"schema_version": 1, "model_call_id": "model-call-1"},
            )
            duplicate_future = pool.submit(
                repo2.append_event_with_auto_sequence,
                event_id="event-retry",
                idempotency_key="model-call-1",
                conversation_id="session-1",
                run_id="run-1",
                event_type="model.started",
                payload={"schema_version": 1, "model_call_id": "tampered"},
            )
            first, first_sequence = first_future.result()
            duplicate, duplicate_sequence = duplicate_future.result()
        second, second_sequence = repo.append_event_with_auto_sequence(
            event_id="event-2",
            idempotency_key="model-call-2",
            conversation_id="session-1",
            run_id="run-1",
            event_type="model.started",
            payload={"schema_version": 1, "model_call_id": "model-call-2"},
        )
    finally:
        repo2.close()

    assert sorted((first, duplicate)) == [False, True]
    assert first_sequence == duplicate_sequence == 1
    assert (second, second_sequence) == (True, 2)
    assert sorted(event.sequence for event in repo.list_events("run-1")) == [1, 2]
    event = repo.list_events("run-1")[0]
    assert event.session_id == "session-1"
    assert event.idempotency_key == "model-call-1"
    assert event.payload["model_call_id"] in {"model-call-1", "tampered"}


def test_memory_conflict_decisions_are_explicit_and_auditable(
    repo: SQLiteRepository,
) -> None:
    service = MemoryService(repo)
    original = service.add_memory(
        scope_type="PROJECT",
        scope_id="paperclaw",
        kind="constraint",
        content="Use the existing repository boundary.",
        source_refs=("operator:user-1",),
    )
    candidate = service.add_memory(
        scope_type="PROJECT",
        scope_id="paperclaw",
        kind="constraint",
        content="Use the existing Context repository boundary.",
        source_refs=("session_event:event-2",),
    )

    decision = service.record_conflict_decision(
        candidate_memory_id=candidate.memory_id,
        conflicting_memory_ids=(original.memory_id,),
        decision="supersede",
    )

    assert decision.decision == "supersede"
    assert decision.source_refs == ("session_event:event-2",)
    active = service.list_memory(scope_type="PROJECT", scope_id="paperclaw")
    assert [item.memory_id for item in active] == [candidate.memory_id]
    history = service.list_memory(
        scope_type="PROJECT", scope_id="paperclaw", include_history=True
    )
    assert {item.memory_id for item in history} >= {
        original.memory_id,
        candidate.memory_id,
    }


def test_memory_source_refs_and_legacy_import_are_idempotent(
    repo: SQLiteRepository,
    tmp_path: Path,
) -> None:
    service = MemoryService(repo)
    typed = service.add_memory(
        scope_type="USER",
        scope_id="user-1",
        kind="user_preference",
        content="Prefer concise status updates.",
        source_refs=(MemorySourceRef("operator", "confirmation-1", "line-2"),),
    )
    assert typed.source_refs == ("operator:confirmation-1#line-2",)

    legacy = FileMemoryStore(tmp_path / "legacy")
    legacy.add("memory", "Keep the repository boundary stable.", category="lesson")
    legacy.add("user", "Use Chinese for project updates.", category="preference")
    snapshot = legacy.snapshot()

    imported = service.import_legacy_snapshot(
        snapshot,
        user_scope_id="user-1",
        project_scope_id="project-1",
    )
    assert len(imported) == 2
    assert service.import_legacy_snapshot(
        snapshot,
        user_scope_id="user-1",
        project_scope_id="project-1",
    ) == ()
    assert all(item.source_refs[0].startswith("legacy_file:") for item in imported)


def test_v4_database_migrates_additively_to_v039(
    tmp_path: Path,
) -> None:
    connection = open_connection(tmp_path / "pre-v039.db")
    connection.execute(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)"
    )
    for version in range(1, 5):
        for statement in MIGRATIONS[version][1]:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, 'test', ?)",
            (version, MIGRATIONS[version][0]),
        )
    result = MigrationRunner(connection).migrate(make_backup=False)
    assert result.ok is True
    assert result.applied_version == 5
    event_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(session_events)")
    }
    snapshot_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(context_snapshots)")
    }
    assert {"turn_id", "idempotency_key", "payload_ref"}.issubset(event_columns)
    assert {"model_call_id", "selected_event_ids", "policy_fingerprint"}.issubset(
        snapshot_columns
    )
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='memory_conflict_decisions'"
    ).fetchone() is not None
    connection.close()


def test_tool_call_and_result_are_one_context_candidate(repo: SQLiteRepository) -> None:
    repo.create_conversation("session-1")
    repo.start_run("run-1", "session-1", "agent", "agent")
    session = SessionService(repo, conversation_id="session-1", run_id="run-1")
    session.emit(
        "tool.started",
        {"tool": "file_read", "call_index": 1, "call_id": "call-1"},
    )
    session.emit(
        "tool.completed",
        {
            "tool": "file_read",
            "call_index": 1,
            "call_id": "call-1",
            "ok": True,
        },
    )

    assembly = ContextOrchestrator(
        repo,
        policy=ContextPolicy(
            max_input_tokens=1_000,
            output_reserve_tokens=100,
            source_quotas=(("tool", 1.0),),
        ),
    ).assemble(
        ContextRequest(
            run_id="run-1",
            conversation_id="session-1",
            step_id="model-1",
            raw_prompt="answer",
            workspace="C:/workspace",
        )
    )

    tool_ids = [
        selection.candidate_id
        for selection in assembly.trace.selected
        if "tool" in selection.candidate_id
    ]
    assert tool_ids == ["tool-group:call-1"]
    assert "tool.started" in assembly.prompt
    assert "tool.completed" in assembly.prompt


def test_model_call_persists_context_snapshot_before_provider_call(
    repo: SQLiteRepository,
    tmp_path: Path,
) -> None:
    executor = ContextOrchestratedAgentRuntimeExecutor(
        FakeModel([done(result="ok")]),
        tmp_path,
        repository=repo,
        enable_verification_gate=False,
    )
    result = QueryEngine(executor, conversation_id="session-snapshot").submit("answer")

    snapshots = repo.list_snapshots(result.run_id)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.session_id == "session-snapshot"
    assert snapshot.model_call_id == "model-1"
    assert snapshot.policy_fingerprint
    assert snapshot.input_tokens == snapshot.estimated_tokens
    assert snapshot.snapshot_id in {
        event.payload.get("context_snapshot_id")
        for event in repo.list_events(result.run_id)
        if event.event_type == "context.snapshot.persisted"
    }


def test_resume_reconstructs_safe_boundary_without_replaying_ambiguous_tool(
    repo: SQLiteRepository,
) -> None:
    repo.create_conversation("session-resume")
    repo.start_run("run-resume", "session-resume", "agent", "agent")
    session = SessionService(repo, conversation_id="session-resume", run_id="run-resume")
    session.emit("model.completed", {"model_call_id": "model-1"})
    safe = session.resume()
    assert safe.can_auto_resume is True
    assert safe.status == "resumable"
    assert safe.permission_mode == "preserve"
    assert safe.last_completed_sequence == 1
    tightened = session.resume(permission_mode="tighten")
    assert tightened.can_auto_resume is True
    assert tightened.permission_mode == "tighten"

    repo.create_conversation("session-ambiguous")
    repo.start_run("run-ambiguous", "session-ambiguous", "agent", "agent")
    ambiguous = SessionService(
        repo,
        conversation_id="session-ambiguous",
        run_id="run-ambiguous",
    )
    ambiguous.emit(
        "tool.started",
        {
            "tool": "file_write",
            "call_index": 1,
            "call_id": "side-effect-1",
            "side_effect": True,
        },
    )
    blocked = ambiguous.resume()
    assert blocked.can_auto_resume is False
    assert blocked.status == "manual_review_required"
    assert blocked.ambiguous_tool_call_ids == ("side-effect-1",)
    assert any(
        event.event_type == "session.resume.blocked"
        for event in ambiguous.list_events()
    )


def test_resume_terminal_session_is_a_noop(repo: SQLiteRepository) -> None:
    repo.create_conversation("session-terminal")
    repo.start_run("run-terminal", "session-terminal", "agent", "agent")
    session = SessionService(repo, conversation_id="session-terminal", run_id="run-terminal")
    session.close(stop_reason="done")
    before = len(session.list_events())
    decision = session.resume()
    assert decision.status == "terminal_noop"
    assert decision.can_auto_resume is False
    assert len(session.list_events()) == before


def test_operator_inspection_is_manifest_only_and_resume_is_safe(repo: SQLiteRepository) -> None:
    repo.create_conversation("session-operator")
    repo.start_run("run-operator", "session-operator", "agent", "agent")
    session = SessionService(repo, conversation_id="session-operator", run_id="run-operator")
    session.emit("model.completed", {"model_call_id": "model-1"})

    operator = SessionOperator(repo)
    inspected = operator.inspect("session-operator")
    assert inspected["session_id"] == "session-operator"
    assert inspected["events"][0]["event_type"] == "model.completed"
    assert "payload" not in inspected["events"][0]
    assert operator.context("session-operator")["latest"] is None
    assert operator.resume("session-operator")["status"] == "resumable"
