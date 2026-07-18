from __future__ import annotations

from types import SimpleNamespace

from paperclaw.desktop.contracts import DesktopRunRequest
from paperclaw.desktop.runtime_factory import DesktopRuntimeFactory
from paperclaw.multiagent.bootstrap import install_cli_subagent_extension
from paperclaw.tools.registry import ToolRegistry


class FakeModel:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.api_key = kwargs.get("api_key", "")
        self.provider = kwargs.get("provider", "fake")
        self.model = kwargs.get("model", "fake-model")

    def complete(self, prompt):  # pragma: no cover - composition test only
        raise AssertionError("model should not be called during composition")


class CapturingEngine:
    def __init__(self, executor, **kwargs) -> None:
        self.executor = executor
        self.kwargs = kwargs


class FakeRegistryComponents:
    def __init__(self) -> None:
        self.tool_registry = ToolRegistry()


class FakeEnvModel:
    @classmethod
    def from_env(cls):
        return object()


def test_desktop_runtime_registers_delegate_tasks_with_fresh_models(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("PAPERCLAW_MEMORY_DIR", str(tmp_path / "memory"))
    created_models: list[FakeModel] = []

    def model_factory(**kwargs):
        model = FakeModel(**kwargs)
        created_models.append(model)
        return model

    request = DesktopRunRequest(
        task="inspect the repository",
        workspace=str(tmp_path),
        base_url="https://provider.invalid/v1",
        api_key="test-secret",
        model="test-model",
        provider="test-provider",
    )
    factory = DesktopRuntimeFactory(
        model_factory=model_factory,
        engine_factory=CapturingEngine,
        conversation_id_factory=lambda: "desktop-test",
    )

    engine = factory.create(request, lambda event, payload: None)

    registry = engine.executor._delegate._registry
    assert "delegate_tasks" in registry.names
    delegation = registry.get("delegate_tasks")
    child_model = delegation._model_factory("worker-1")
    assert child_model is not created_models[0]
    assert child_model.kwargs["api_key"] == "test-secret"
    assert child_model.kwargs["model"] == "test-model"
    assert engine.kwargs["conversation_id"] == "desktop-test"


def test_cli_bootstrap_registers_delegation_idempotently() -> None:
    components = FakeRegistryComponents()
    build_calls = []

    def build_memory_runtime(workspace):
        build_calls.append(workspace)
        return components

    cli_module = SimpleNamespace(
        build_memory_runtime=build_memory_runtime,
        OpenAICompatibleModel=FakeEnvModel,
    )

    install_cli_subagent_extension(cli_module)
    installed_builder = cli_module.build_memory_runtime
    install_cli_subagent_extension(cli_module)

    returned = cli_module.build_memory_runtime("workspace")
    assert returned is components
    assert cli_module.build_memory_runtime is installed_builder
    assert build_calls == ["workspace"]
    assert components.tool_registry.names == ("delegate_tasks",)
