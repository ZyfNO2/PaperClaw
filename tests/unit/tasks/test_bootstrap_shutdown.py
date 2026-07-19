from __future__ import annotations

from pathlib import Path

import pytest

import paperclaw.cli
from paperclaw.entrypoint import main as entrypoint_main
from paperclaw.tasks.bootstrap import (
    get_or_create_task_runtime,
    shutdown_task_runtimes,
)


def _runtime(database: Path, *, cache_key: str):
    return get_or_create_task_runtime(
        lambda _agent_id: None,  # type: ignore[return-value]
        cache_key=cache_key,
        database=database,
        worker_id=f"test-{cache_key}",
        max_concurrency=1,
        provider_concurrency=1,
    )


def test_shutdown_task_runtimes_stops_threads_and_clears_cache(
    tmp_path: Path,
) -> None:
    shutdown_task_runtimes()
    first = _runtime(tmp_path / "tasks.sqlite3", cache_key="first")
    assert first.supervisor.running() is True

    shutdown_task_runtimes(timeout=5)
    assert first.supervisor.running() is False

    second = _runtime(tmp_path / "tasks.sqlite3", cache_key="first")
    try:
        assert second is not first
        assert second.supervisor.running() is True
    finally:
        shutdown_task_runtimes(timeout=5)
    assert second.supervisor.running() is False


def test_shutdown_task_runtimes_is_idempotent() -> None:
    shutdown_task_runtimes()
    shutdown_task_runtimes()
    with pytest.raises(ValueError, match="non-negative"):
        shutdown_task_runtimes(timeout=-1)


def test_cli_entrypoint_stops_runtime_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_task_runtimes()
    observed = {}

    def fake_main(_argv):
        observed["runtime"] = _runtime(
            tmp_path / "cli-tasks.sqlite3",
            cache_key="cli-return",
        )
        assert observed["runtime"].supervisor.running() is True
        return 7

    monkeypatch.setattr(paperclaw.cli, "main", fake_main)
    assert entrypoint_main([]) == 7
    assert observed["runtime"].supervisor.running() is False


def test_cli_entrypoint_stops_runtime_when_cli_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_task_runtimes()
    observed = {}

    def fake_main(_argv):
        observed["runtime"] = _runtime(
            tmp_path / "cli-error-tasks.sqlite3",
            cache_key="cli-error",
        )
        raise RuntimeError("cli failure")

    monkeypatch.setattr(paperclaw.cli, "main", fake_main)
    with pytest.raises(RuntimeError, match="cli failure"):
        entrypoint_main([])
    assert observed["runtime"].supervisor.running() is False
