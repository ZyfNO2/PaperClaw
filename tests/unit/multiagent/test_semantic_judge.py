from __future__ import annotations

import json

from paperclaw.models.base import ModelTurn
from paperclaw.models.reliability import ProviderError
from paperclaw.multiagent.contracts import AgentTask, TeamBudget
from paperclaw.multiagent.semantic_coordinator import SemanticCoordinator
from paperclaw.multiagent.semantic_judge import SemanticAcceptanceJudge


class SequenceModel:
    provider = "fake-provider"
    model = "fake-judge"

    def __init__(self, values):
        self.values = list(values)
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> ModelTurn:
        self.calls += 1
        self.prompts.append(prompt)
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, dict):
            value = json.dumps(value)
        return ModelTurn(str(value))


def _task() -> AgentTask:
    return AgentTask(
        task_id="read-only",
        title="Read only analysis",
        objective="Inspect the permission boundary and explain one denial path.",
        acceptance_criteria=[
            "Cite the inspected module",
            "Explain one permission denial path",
        ],
        allowed_paths=["src/paperclaw/mcp"],
        writable_paths=[],
        allowed_tools=["file_read", "grep"],
    )


def _evaluate(model: SequenceModel):
    return SemanticAcceptanceJudge(model).evaluate(
        _task(),
        worker_summary="Inspected policy.py; missing policy denies the request.",
        deterministic_result=None,
        changed_files=[],
        unresolved_items=[],
    )


def test_semantic_judge_accepts_on_first_pass() -> None:
    model = SequenceModel(
        [{"status": "passed", "reason_code": "criteria_met", "summary": "Both criteria are covered."}]
    )

    result = _evaluate(model)

    assert result.status == "passed"
    assert result.attempt_count == 1
    assert result.provider == "fake-provider"
    assert result.model == "fake-judge"
    assert model.calls == 1


def test_semantic_judge_requires_confirmation_for_rejection() -> None:
    model = SequenceModel(
        [
            {"status": "rejected", "reason_code": "missing_citation", "summary": "No module citation."},
            {"status": "rejected", "reason_code": "missing_citation", "summary": "Citation still missing."},
        ]
    )

    result = _evaluate(model)

    assert result.status == "rejected"
    assert result.attempt_count == 2
    assert model.calls == 2


def test_semantic_judge_disagreement_is_inconclusive_not_failure() -> None:
    model = SequenceModel(
        [
            {"status": "rejected", "reason_code": "missing_path", "summary": "Path is unclear."},
            {"status": "passed", "reason_code": "path_present", "summary": "The path is present."},
        ]
    )

    result = _evaluate(model)

    assert result.status == "inconclusive"
    assert result.reason_code == "judge_disagreement"
    assert result.attempt_count == 2


def test_semantic_judge_retries_only_retriable_provider_failure() -> None:
    transient = ProviderError(
        "rate limited",
        code="RATE_LIMITED",
        retriable=True,
        status_code=429,
    )
    model = SequenceModel(
        [
            transient,
            {"status": "passed", "reason_code": "criteria_met", "summary": "Recovered and passed."},
        ]
    )

    result = _evaluate(model)

    assert result.status == "passed"
    assert result.attempt_count == 2
    assert model.calls == 2


def test_semantic_judge_does_not_treat_post_transient_lone_rejection_as_confirmed() -> None:
    transient = ProviderError(
        "temporarily unavailable",
        code="PROVIDER_TEMPORARILY_UNAVAILABLE",
        retriable=True,
        status_code=503,
    )
    model = SequenceModel(
        [
            transient,
            {"status": "rejected", "reason_code": "missing_path", "summary": "Path is unclear."},
        ]
    )

    result = _evaluate(model)

    assert result.status == "inconclusive"
    assert result.reason_code == "rejection_unconfirmed"
    assert result.attempt_count == 2
    assert model.calls == 2


def test_semantic_judge_does_not_retry_non_retriable_provider_failure() -> None:
    auth = ProviderError(
        "authentication failed",
        code="AUTHENTICATION_FAILED",
        retriable=False,
        status_code=401,
    )
    model = SequenceModel([auth])

    result = _evaluate(model)

    assert result.status == "provider_error"
    assert result.reason_code == "authentication_failed"
    assert result.attempt_count == 1
    assert model.calls == 1


def test_semantic_judge_invalid_contract_is_protocol_error_without_retry() -> None:
    model = SequenceModel(["not-json", {"status": "passed"}])

    result = _evaluate(model)

    assert result.status == "protocol_error"
    assert result.reason_code == "invalid_judge_output"
    assert result.attempt_count == 1
    assert model.calls == 1


def test_semantic_coordinator_uses_distinct_judge_factory_and_reserves_budget(tmp_path) -> None:
    execution_models: list[tuple[str, SequenceModel]] = []
    judge_models: list[tuple[str, SequenceModel]] = []

    def execution_factory(agent_id: str):
        model = SequenceModel([])
        execution_models.append((agent_id, model))
        return model

    def judge_factory(agent_id: str):
        model = SequenceModel([])
        judge_models.append((agent_id, model))
        return model

    coordinator = SemanticCoordinator(
        execution_factory,
        tmp_path,
        budget=TeamBudget(max_total_model_calls=20),
        judge_model_factory=judge_factory,
    )

    worker = coordinator._make_worker("worker-0")

    assert execution_models[0][0] == "worker-0"
    assert judge_models[0][0] == "judge-worker-0"
    assert worker._model is execution_models[0][1]
    assert worker._judge_model is judge_models[0][1]
    assert coordinator._model_call_upper_bound(_task()) == _task().max_steps + 4
