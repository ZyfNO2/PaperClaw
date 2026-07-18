from __future__ import annotations

from pathlib import Path
from typing import Any

from paperclaw.service.contracts import ServiceRunRequest
from paperclaw.service.runtime_factory import ServiceRuntimeFactory


class _Model:
    provider = "test"
    model = "test-model"
    api_key = ""

    def complete(self, _prompt: str) -> Any:  # pragma: no cover - construction only
        raise AssertionError("model must not be called during factory construction")


def _capture_executor(executor, **_kwargs):
    return executor


def _registry_names(executor) -> tuple[str, ...]:
    return executor._delegate._registry.names


def test_unauthenticated_service_disables_personal_memory_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory_root = tmp_path / "memories"
    monkeypatch.setenv("PAPERCLAW_MEMORY_DIR", str(memory_root))
    monkeypatch.delenv("PAPERCLAW_SERVICE_PERSONAL_MEMORY_ENABLED", raising=False)

    executor = ServiceRuntimeFactory(
        model_factory=_Model,
        engine_factory=_capture_executor,
    ).create(
        ServiceRunRequest(task="inspect repository", workspace=str(workspace)),
        lambda _event, _payload: None,
    )

    assert "memory" not in _registry_names(executor)
    assert executor.context_source_snapshot is not None
    assert not memory_root.exists()


def test_trusted_deployment_can_explicitly_enable_personal_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory_root = tmp_path / "memories"
    monkeypatch.setenv("PAPERCLAW_MEMORY_DIR", str(memory_root))

    executor = ServiceRuntimeFactory(
        model_factory=_Model,
        engine_factory=_capture_executor,
        enable_personal_memory=True,
    ).create(
        ServiceRunRequest(task="inspect repository", workspace=str(workspace)),
        lambda _event, _payload: None,
    )

    assert "memory" in _registry_names(executor)
    assert executor.context_source_snapshot is not None


def test_service_personal_memory_environment_flag_is_strict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("PAPERCLAW_SERVICE_PERSONAL_MEMORY_ENABLED", "not-a-bool")

    try:
        ServiceRuntimeFactory(model_factory=_Model, engine_factory=_capture_executor)
    except ValueError as exc:
        assert "PAPERCLAW_SERVICE_PERSONAL_MEMORY_ENABLED" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid boolean deployment configuration was accepted")
