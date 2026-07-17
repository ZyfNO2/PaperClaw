from __future__ import annotations

import os

from paperclaw.desktop.contracts import DesktopRunRequest
from paperclaw.desktop.runtime_factory import DesktopRuntimeFactory


class FakeModel:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    @classmethod
    def from_env(cls):
        raise AssertionError("desktop runtime must not use from_env")


class FakeExecutor:
    def __init__(self, model, workspace, **kwargs) -> None:
        self.model = model
        self.workspace = workspace
        self.kwargs = kwargs


class FakeEngine:
    def __init__(self, executor, *, conversation_id, event_handler) -> None:
        self.executor = executor
        self.conversation_id = conversation_id
        self.event_handler = event_handler


def _factory() -> DesktopRuntimeFactory:
    return DesktopRuntimeFactory(
        model_factory=FakeModel,
        executor_factory=FakeExecutor,
        engine_factory=FakeEngine,
        conversation_id_factory=lambda: "desktop-test",
    )


def test_runtime_factory_uses_explicit_values_without_mutating_environment(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PAPERCLAW_API_KEY", "unrelated-env-key")
    request = DesktopRunRequest.from_mapping(
        {
            "task": "test",
            "workspace": str(tmp_path),
            "base_url": "https://provider.invalid/v1",
            "api_key": "run-scoped-key",
            "model": "model-a",
            "provider": "provider-a",
        }
    )
    observed: list[tuple[str, dict]] = []

    engine = _factory().create(
        request,
        lambda event, payload: observed.append((event, payload)),
    )

    assert engine.conversation_id == "desktop-test"
    assert engine.executor.workspace == str(tmp_path.resolve())
    assert engine.executor.model.kwargs["api_key"] == "run-scoped-key"
    assert engine.executor.model.kwargs["base_url"] == "https://provider.invalid/v1"
    assert engine.executor.model.kwargs["model"] == "model-a"
    assert engine.executor.model.kwargs["provider"] == "provider-a"
    assert engine.executor.model.kwargs["retry_policy"].max_attempts == 3
    assert engine.executor.kwargs["enable_verification_gate"] is True
    assert os.environ["PAPERCLAW_API_KEY"] == "unrelated-env-key"

    engine.event_handler("run.started", {"run_id": "run-1", "sequence": 10})
    engine.executor.kwargs["legacy_event_handler"](
        "verification_completed",
        {
            "result": {
                "status": "passed",
                "summary": "safe summary",
                "checks": [{"observed": "must not cross"}],
            }
        },
    )
    assert observed[0] == (
        "run.started",
        {"run_id": "run-1", "sequence": 1, "query_sequence": 10},
    )
    assert observed[1][0] == "verification.completed"
    assert observed[1][1]["result"]["summary"] == "safe summary"
    assert "checks" not in observed[1][1]["result"]


def test_runtime_factory_forwards_disabled_verify_and_reflection_gate(tmp_path) -> None:
    request = DesktopRunRequest.from_mapping(
        {
            "task": "hello",
            "workspace": str(tmp_path),
            "base_url": "https://provider.invalid/v1",
            "api_key": "run-scoped-key",
            "model": "model-a",
            "provider": "provider-a",
            "enable_verification_gate": False,
        }
    )

    engine = _factory().create(request, lambda _event, _payload: None)

    assert engine.executor.kwargs["enable_verification_gate"] is False
