from __future__ import annotations

from pathlib import Path

from paperclaw.context.repository import SQLiteRepository
from paperclaw.harness import AgentRuntimeExecutor, QueryEngine
from paperclaw.trace import RepositoryTraceReader


class SecretFailingModel:
    provider = "mistral"
    model = "mistral-test"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def complete(self, prompt: str):
        raise RuntimeError(f"provider rejected Bearer {self.api_key}")


def test_provider_secret_is_redacted_before_sqlite_persistence(
    tmp_path: Path,
) -> None:
    secret = "mistral-secret-that-must-not-persist"
    database = tmp_path / "paperclaw.db"
    repository = SQLiteRepository(database, migrate=True)
    try:
        result = QueryEngine(
            AgentRuntimeExecutor(
                SecretFailingModel(secret),
                tmp_path,
                repository=repository,
                enable_verification_gate=False,
            ),
            conversation_id="conv-secret-boundary",
        ).submit("fail without leaking credentials")

        raw_events = repository.list_events(result.run_id)
        trace = RepositoryTraceReader(repository).get_run_trace(
            result.run_id,
            require_terminal=True,
        )
    finally:
        repository.close()

    model_failure = next(
        event for event in raw_events if event.event_type == "model.failed"
    )
    assert result.status == "failed"
    assert model_failure.payload["provider"] == "mistral"
    assert model_failure.payload["model"] == "mistral-test"
    assert model_failure.payload["error_message"] == "provider rejected Bearer <REDACTED>"
    assert trace[-1].event_type == "run.failed"
    assert secret not in database.read_text(encoding="latin-1")
