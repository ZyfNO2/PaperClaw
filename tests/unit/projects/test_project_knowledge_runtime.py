from __future__ import annotations

from pathlib import Path
import time

import pytest

from paperclaw.projects import (
    ProjectIndexPolicy,
    ProjectKnowledgeRuntime,
    ProjectKnowledgeUnavailableError,
    ProjectKnowledgeWatcher,
    ProjectManifest,
    ProjectManifestStore,
    build_project_index,
)


def _project(tmp_path: Path) -> tuple[ProjectManifestStore, ProjectManifest, Path]:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    document = knowledge / "facts.md"
    document.write_text("alpha evidence\n", encoding="utf-8")
    manifest = ProjectManifest(
        schema_version=1,
        project_id="demo",
        name="Demo",
        instruction_files=(),
        knowledge_paths=("knowledge",),
    )
    store = ProjectManifestStore(tmp_path)
    store.save(manifest)
    return store, manifest, document


def test_require_current_rejects_stale_index(tmp_path: Path) -> None:
    store, manifest, document = _project(tmp_path)
    build_project_index(store, manifest)
    runtime = ProjectKnowledgeRuntime(store, manifest)
    assert runtime.inspect().retriever_available is True

    document.write_text("changed evidence\n", encoding="utf-8")
    snapshot = runtime.inspect()
    assert snapshot.status.reason == "index_stale"
    assert snapshot.retriever_available is False
    with pytest.raises(ProjectKnowledgeUnavailableError, match="index_stale"):
        runtime.create_retriever()


def test_allow_stale_can_open_existing_index_but_reports_status(tmp_path: Path) -> None:
    store, manifest, document = _project(tmp_path)
    build_project_index(store, manifest)
    document.write_text("changed evidence\n", encoding="utf-8")
    runtime = ProjectKnowledgeRuntime(
        store,
        manifest,
        policy=ProjectIndexPolicy.ALLOW_STALE,
    )

    snapshot = runtime.inspect()
    assert snapshot.status.current is False
    assert snapshot.retriever_available is True
    retriever = runtime.create_retriever()
    assert retriever is not None
    retriever.close()


def test_disabled_policy_never_opens_or_rebuilds(tmp_path: Path) -> None:
    store, manifest, _document = _project(tmp_path)
    runtime = ProjectKnowledgeRuntime(
        store,
        manifest,
        policy=ProjectIndexPolicy.DISABLED,
    )

    assert runtime.inspect().retriever_available is False
    assert runtime.create_retriever() is None
    with pytest.raises(ProjectKnowledgeUnavailableError, match="disabled"):
        runtime.rebuild()


def test_refresh_if_stale_rebuilds_once(tmp_path: Path) -> None:
    store, manifest, document = _project(tmp_path)
    runtime = ProjectKnowledgeRuntime(store, manifest)
    first, rebuilt = runtime.refresh_if_stale()
    assert rebuilt is True
    assert first.status.current is True

    second, rebuilt_again = runtime.refresh_if_stale()
    assert rebuilt_again is False
    assert second.status.current is True

    document.write_text("beta evidence\n", encoding="utf-8")
    third, rebuilt_changed = runtime.refresh_if_stale()
    assert rebuilt_changed is True
    assert third.status.current is True


def test_watcher_detects_change_and_can_rebuild_explicitly(tmp_path: Path) -> None:
    store, manifest, document = _project(tmp_path)
    build_project_index(store, manifest)
    runtime = ProjectKnowledgeRuntime(store, manifest)
    events = []
    watcher = ProjectKnowledgeWatcher(
        runtime,
        poll_seconds=0.05,
        rebuild_on_change=True,
        on_event=events.append,
    )

    document.write_text("gamma evidence\n", encoding="utf-8")
    event = watcher.poll_once()
    assert event is not None
    assert event.rebuilt is True
    assert event.current_reason == "current"
    assert runtime.inspect().status.current is True
    assert events == [event]


def test_watcher_start_stop_is_explicit_and_bounded(tmp_path: Path) -> None:
    store, manifest, _document = _project(tmp_path)
    build_project_index(store, manifest)
    watcher = ProjectKnowledgeWatcher(
        ProjectKnowledgeRuntime(store, manifest), poll_seconds=0.05
    )

    assert watcher.running() is False
    watcher.start()
    time.sleep(0.08)
    assert watcher.running() is True
    watcher.stop(timeout=2.0)
    assert watcher.running() is False
