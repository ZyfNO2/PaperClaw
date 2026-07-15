from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from paperclaw.context.repository import SQLiteRepository
from paperclaw.harness import RunLimits
from paperclaw.replay import (
    LIVE_REPLAY_CONFIRMATION,
    LiveReplayAgentRuntimeExecutor,
    LiveReplayError,
    LiveReplayPolicy,
    execute_live_replay,
    prepare_live_replay,
)
from paperclaw.tools.registry import ToolRegistry
from paperclaw.trace import TraceEvent
from tests.helpers import FakeModel, done


class _Reader:
    def __init__(self, terminal: str = "run.completed") -> None:
        status = terminal.rsplit(".", 1)[-1]
        self.events = (
            TraceEvent(
                event_id="source-1",
                sequence=1,
                occurred_at="2026-07-16T00:00:00+00:00",
                conversation_id="source-conversation",
                run_id="source-run",
                event_type="run.started",
                component="harness",
                status="started",
            ),
            TraceEvent(
                event_id="source-2",
                sequence=2,
                occurred_at="2026-07-16T00:00:01+00:00",
                conversation_id="source-conversation",
                run_id="source-run",
                event_type=terminal,
                component="harness",
                status=status,
            ),
        )

    def get_run_trace(self, run_id: str, **_kwargs):
        assert run_id == "source-run"
        return self.events

    def iter_run_trace(self, run_id: str, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


def _policy(**overrides) -> LiveReplayPolicy:
    values = {
        "enabled": True,
        "confirmation": LIVE_REPLAY_CONFIRMATION,
        "allowed_tools": (),
        "limits": RunLimits(
            max_steps=3,
            max_model_calls=2,
            max_tool_calls=1,
        ),
    }
    values.update(overrides)
    return LiveReplayPolicy(**values)


def test_live_replay_requires_explicit_authorization() -> None:
    with pytest.raises(LiveReplayError, match="disabled"):
        prepare_live_replay(
            _Reader(),
            "source-run",
            "new explicit task",
            policy=LiveReplayPolicy(),
        )

    with pytest.raises(LiveReplayError, match="confirmation"):
        prepare_live_replay(
            _Reader(),
            "source-run",
            "new explicit task",
            policy=LiveReplayPolicy(enabled=True, confirmation="wrong"),
        )

    with pytest.raises(LiveReplayError, match="mutating tools"):
        prepare_live_replay(
            _Reader(),
            "source-run",
            "new explicit task",
            policy=_policy(allowed_tools=("bash",)),
        )


def test_live_replay_rejects_noncompleted_source_by_default() -> None:
    with pytest.raises(LiveReplayError, match="not completed"):
        prepare_live_replay(
            _Reader("run.failed"),
            "source-run",
            "new explicit task",
            policy=_policy(),
        )


def test_live_replay_creates_new_run_with_bounded_provenance(
    tmp_path: Path,
) -> None:
    task = "finish directly without tools"
    plan = prepare_live_replay(
        _Reader(),
        "source-run",
        task,
        policy=_policy(),
    )
    assert task not in str(plan.to_dict())
    assert plan.prompt_chars == len(task)
    assert len(plan.prompt_sha256) == 64

    repository = SQLiteRepository(tmp_path / "target.db", migrate=True)
    try:
        executor = LiveReplayAgentRuntimeExecutor(
            FakeModel([done(result="live-replay-ok")]),
            tmp_path,
            plan=plan,
            registry=ToolRegistry([]),
            repository=repository,
            enable_verification_gate=False,
        )
        result = execute_live_replay(plan, executor)
        events = repository.list_events(result.run_result.run_id)
    finally:
        repository.close()

    assert result.run_result.status == "completed"
    assert result.run_result.run_id != plan.source_run_id
    assert events[0].event_type == "run.started"
    assert events[0].payload["live_replay"] is True
    assert events[0].payload["source_run_id"] == "source-run"
    assert events[0].payload["prompt_sha256"] == plan.prompt_sha256
    assert events[0].payload["allowed_tools"] == []
    assert task not in str(events[0].payload)


def test_live_replay_does_not_modify_source_database(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    source_repository = SQLiteRepository(source_path, migrate=True)
    source_repository.close()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    plan = prepare_live_replay(
        _Reader(),
        "source-run",
        "new isolated task",
        policy=_policy(),
    )
    target_path = tmp_path / "target.db"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target_repository = SQLiteRepository(target_path, migrate=True)
    try:
        executor = LiveReplayAgentRuntimeExecutor(
            FakeModel([done(result="ok")]),
            workspace,
            plan=plan,
            registry=ToolRegistry([]),
            repository=target_repository,
            enable_verification_gate=False,
        )
        result = execute_live_replay(plan, executor)
    finally:
        target_repository.close()

    after = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert after == before
    assert target_path.exists()
    assert result.run_result.run_id != plan.source_run_id
    assert plan.conversation_id != "source-conversation"
