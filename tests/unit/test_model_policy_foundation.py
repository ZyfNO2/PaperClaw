from __future__ import annotations

import itertools

import pytest

from paperclaw.model_policy import (
    FallbackAttempt,
    ModelCandidate,
    ModelFailureCategory,
    ModelPolicyError,
    ModelRequestProfile,
    StaticModelPolicyRouter,
)


def candidate(
    provider: str,
    model: str,
    *,
    capabilities: frozenset[str] = frozenset({"chat"}),
    context: int = 32_000,
    structured: bool = True,
    input_cost: float = 1.0,
    output_cost: float = 2.0,
    rank: int = 100,
    enabled: bool = True,
) -> ModelCandidate:
    return ModelCandidate(
        provider_id=provider,
        model_id=model,
        capabilities=capabilities,
        context_window_tokens=context,
        supports_structured_output=structured,
        input_cost_usd_per_million=input_cost,
        output_cost_usd_per_million=output_cost,
        preference_rank=rank,
        enabled=enabled,
    )


def test_routing_is_deterministic_across_candidate_permutations() -> None:
    profile = ModelRequestProfile(
        required_capabilities=frozenset({"chat"}),
        estimated_input_tokens=5_000,
        output_reserve_tokens=1_000,
        max_candidates=3,
    )
    candidates = (
        candidate("provider-b", "model-b", rank=20, input_cost=0.5),
        candidate("provider-a", "model-a", rank=10, input_cost=2.0),
        candidate("provider-c", "model-c", rank=20, input_cost=0.2),
    )
    router = StaticModelPolicyRouter()
    baseline = router.route(profile, candidates)

    for permutation in itertools.permutations(candidates):
        decision = router.route(profile, permutation)
        assert decision.primary_model == baseline.primary_model
        assert decision.fallback_chain == baseline.fallback_chain
        assert decision.fingerprint == baseline.fingerprint
        assert decision.to_metadata() == baseline.to_metadata()

    assert baseline.primary_model == "provider-a:model-a"
    assert baseline.fallback_chain == (
        "provider-c:model-c",
        "provider-b:model-b",
    )


def test_capability_context_structured_output_cost_and_disabled_filters() -> None:
    profile = ModelRequestProfile(
        required_capabilities=frozenset({"chat", "tools"}),
        estimated_input_tokens=8_000,
        output_reserve_tokens=2_000,
        structured_output_required=True,
        cost_ceiling_usd=0.05,
        max_candidates=5,
    )
    candidates = (
        candidate(
            "ok",
            "model",
            capabilities=frozenset({"chat", "tools"}),
            context=16_000,
            input_cost=1.0,
            output_cost=1.0,
        ),
        candidate("missing", "tools", capabilities=frozenset({"chat"})),
        candidate(
            "small",
            "context",
            capabilities=frozenset({"chat", "tools"}),
            context=9_000,
        ),
        candidate(
            "no",
            "structured",
            capabilities=frozenset({"chat", "tools"}),
            structured=False,
        ),
        candidate(
            "too",
            "expensive",
            capabilities=frozenset({"chat", "tools"}),
            input_cost=10.0,
            output_cost=10.0,
        ),
        candidate(
            "disabled",
            "model",
            capabilities=frozenset({"chat", "tools"}),
            enabled=False,
        ),
    )
    decision = StaticModelPolicyRouter().route(profile, candidates)
    excluded = {item.qualified_name: item.reason for item in decision.excluded}

    assert decision.primary_model == "ok:model"
    assert excluded == {
        "disabled:model": "disabled",
        "missing:tools": "missing_capability:tools",
        "no:structured": "structured_output",
        "small:context": "context_window",
        "too:expensive": "cost_ceiling",
    }


def test_explicit_override_pins_primary_but_remains_fail_closed() -> None:
    router = StaticModelPolicyRouter()
    candidates = (
        candidate("preferred", "cheap", rank=1),
        candidate("manual", "override", rank=100),
    )
    profile = ModelRequestProfile(
        required_capabilities=frozenset({"chat"}),
        explicit_model="manual:override",
        max_candidates=2,
    )
    decision = router.route(profile, candidates)

    assert decision.primary_model == "manual:override"
    assert decision.fallback_chain == ("preferred:cheap",)
    assert decision.explicit_override is True

    with pytest.raises(ModelPolicyError) as missing:
        router.route(
            ModelRequestProfile(explicit_model="unknown:model"),
            candidates,
        )
    assert missing.value.code == "EXPLICIT_MODEL_NOT_FOUND"

    with pytest.raises(ModelPolicyError) as ineligible:
        router.route(
            ModelRequestProfile(
                required_capabilities=frozenset({"vision"}),
                explicit_model="manual:override",
            ),
            candidates,
        )
    assert ineligible.value.code == "EXPLICIT_MODEL_INELIGIBLE"


def test_fallback_chain_is_bounded_and_can_be_disabled() -> None:
    candidates = tuple(candidate("provider", f"model-{index}", rank=index) for index in range(8))
    router = StaticModelPolicyRouter()

    bounded = router.route(ModelRequestProfile(max_candidates=3), candidates)
    assert bounded.primary_model == "provider:model-0"
    assert bounded.fallback_chain == ("provider:model-1", "provider:model-2")

    disabled = router.route(
        ModelRequestProfile(max_candidates=8, allow_fallback=False),
        candidates,
    )
    assert disabled.primary_model == "provider:model-0"
    assert disabled.fallback_chain == ()


@pytest.mark.parametrize(
    "category",
    [
        ModelFailureCategory.AUTHENTICATION,
        ModelFailureCategory.PERMISSION,
        ModelFailureCategory.INVALID_REQUEST,
        ModelFailureCategory.CONTEXT_OVERFLOW,
        ModelFailureCategory.STRUCTURED_OUTPUT,
        ModelFailureCategory.UNKNOWN,
    ],
)
def test_non_retriable_failure_categories_never_fallback(
    category: ModelFailureCategory,
) -> None:
    router = StaticModelPolicyRouter()
    decision = router.route(
        ModelRequestProfile(max_candidates=2),
        (candidate("p", "primary", rank=1), candidate("p", "fallback", rank=2)),
    )
    next_model = router.next_fallback(
        decision,
        (FallbackAttempt(decision.primary_model, category, "failure"),),
    )
    assert next_model is None


@pytest.mark.parametrize(
    "category",
    [
        ModelFailureCategory.NETWORK,
        ModelFailureCategory.RATE_LIMIT,
        ModelFailureCategory.SERVER_ERROR,
    ],
)
def test_transient_failure_categories_advance_once_through_bounded_chain(
    category: ModelFailureCategory,
) -> None:
    router = StaticModelPolicyRouter()
    decision = router.route(
        ModelRequestProfile(max_candidates=3),
        (
            candidate("p", "primary", rank=1),
            candidate("p", "fallback-a", rank=2),
            candidate("p", "fallback-b", rank=3),
        ),
    )
    first = FallbackAttempt(decision.primary_model, category, "transient")
    assert router.next_fallback(decision, (first,)) == "p:fallback-a"

    second = FallbackAttempt("p:fallback-a", category, "transient")
    assert router.next_fallback(decision, (first, second)) == "p:fallback-b"

    third = FallbackAttempt("p:fallback-b", category, "transient")
    assert router.next_fallback(decision, (first, second, third)) is None


def test_duplicate_candidates_and_no_eligible_model_fail_closed() -> None:
    router = StaticModelPolicyRouter()
    duplicate = candidate("same", "model")
    with pytest.raises(ModelPolicyError) as duplicated:
        router.route(ModelRequestProfile(), (duplicate, duplicate))
    assert duplicated.value.code == "DUPLICATE_CANDIDATE"

    with pytest.raises(ModelPolicyError) as empty:
        router.route(
            ModelRequestProfile(required_capabilities=frozenset({"vision"})),
            (candidate("chat", "only"),),
        )
    assert empty.value.code == "NO_ELIGIBLE_MODEL"


def test_decision_metadata_is_structured_and_contains_no_hidden_input() -> None:
    profile = ModelRequestProfile(
        required_capabilities=frozenset({"chat"}),
        estimated_input_tokens=1_000,
        output_reserve_tokens=500,
        cost_ceiling_usd=1.0,
    )
    decision = StaticModelPolicyRouter().route(
        profile,
        (candidate("provider", "model", input_cost=2.0, output_cost=4.0),),
    )
    metadata = decision.to_metadata()

    assert metadata["primary_model"] == "provider:model"
    assert metadata["request_fingerprint"] == profile.fingerprint
    assert metadata["estimated_costs"]["provider:model"] == pytest.approx(0.004)
    assert "prompt" not in metadata
    assert "reasoning" not in metadata
