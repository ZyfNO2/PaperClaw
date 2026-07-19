from __future__ import annotations

from paperclaw.multiagent.judge_factory import build_judge_model_from_env


def test_judge_factory_falls_back_to_execution_provider_env(monkeypatch) -> None:
    monkeypatch.setenv("PAPERCLAW_API_KEY", "execution-key")
    monkeypatch.setenv("PAPERCLAW_BASE_URL", "https://execution.invalid/v1")
    monkeypatch.setenv("PAPERCLAW_MODEL", "execution-model")
    monkeypatch.setenv("PAPERCLAW_PROVIDER", "execution-provider")
    for name in (
        "PAPERCLAW_JUDGE_API_KEY",
        "PAPERCLAW_JUDGE_BASE_URL",
        "PAPERCLAW_JUDGE_MODEL",
        "PAPERCLAW_JUDGE_PROVIDER",
        "PAPERCLAW_JUDGE_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    model = build_judge_model_from_env()

    assert model.api_key == "execution-key"
    assert model.base_url == "https://execution.invalid/v1"
    assert model.model == "execution-model"
    assert model.provider == "execution-provider"
    assert model.retry_policy.max_attempts == 1


def test_judge_factory_supports_independent_provider_overrides(monkeypatch) -> None:
    monkeypatch.setenv("PAPERCLAW_API_KEY", "execution-key")
    monkeypatch.setenv("PAPERCLAW_BASE_URL", "https://execution.invalid/v1")
    monkeypatch.setenv("PAPERCLAW_MODEL", "execution-model")
    monkeypatch.setenv("PAPERCLAW_PROVIDER", "execution-provider")
    monkeypatch.setenv("PAPERCLAW_JUDGE_API_KEY", "judge-key")
    monkeypatch.setenv("PAPERCLAW_JUDGE_BASE_URL", "https://judge.invalid/v1")
    monkeypatch.setenv("PAPERCLAW_JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("PAPERCLAW_JUDGE_PROVIDER", "judge-provider")
    monkeypatch.setenv("PAPERCLAW_JUDGE_TIMEOUT_SECONDS", "45")

    model = build_judge_model_from_env()

    assert model.api_key == "judge-key"
    assert model.base_url == "https://judge.invalid/v1"
    assert model.model == "judge-model"
    assert model.provider == "judge-provider"
    assert model.timeout == 45
    assert model.retry_policy.max_attempts == 1
