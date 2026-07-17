"""Deterministic static Model Policy router for v0.10 foundation."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

from paperclaw.model_policy.contracts import (
    FallbackAttempt,
    ModelCandidate,
    ModelExclusion,
    ModelFailureCategory,
    ModelPolicyDecision,
    ModelPolicyError,
    ModelRequestProfile,
    POLICY_VERSION,
)

_FALLBACK_ALLOWED = frozenset(
    {
        ModelFailureCategory.NETWORK,
        ModelFailureCategory.RATE_LIMIT,
        ModelFailureCategory.SERVER_ERROR,
    }
)


class StaticModelPolicyRouter:
    """Select a bounded, deterministic model chain from structured facts only."""

    def __init__(self, *, policy_version: str = POLICY_VERSION) -> None:
        if not policy_version.strip():
            raise ValueError("policy_version must be non-empty")
        self.policy_version = policy_version

    def route(
        self,
        profile: ModelRequestProfile,
        candidates: Iterable[ModelCandidate],
    ) -> ModelPolicyDecision:
        frozen = tuple(candidates)
        by_name: dict[str, ModelCandidate] = {}
        for candidate in frozen:
            if candidate.qualified_name in by_name:
                raise ModelPolicyError(
                    f"duplicate model candidate: {candidate.qualified_name}",
                    code="DUPLICATE_CANDIDATE",
                )
            by_name[candidate.qualified_name] = candidate

        eligible: list[ModelCandidate] = []
        excluded: list[ModelExclusion] = []
        for candidate in frozen:
            reason = self._exclusion_reason(profile, candidate)
            if reason is None:
                eligible.append(candidate)
            else:
                excluded.append(ModelExclusion(candidate.qualified_name, reason))

        eligible.sort(key=lambda item: self._sort_key(profile, item))
        excluded.sort(key=lambda item: item.qualified_name)

        explicit_override = profile.explicit_model is not None
        if explicit_override:
            selected = by_name.get(profile.explicit_model or "")
            if selected is None:
                raise ModelPolicyError(
                    f"explicit model is not configured: {profile.explicit_model}",
                    code="EXPLICIT_MODEL_NOT_FOUND",
                )
            reason = self._exclusion_reason(profile, selected)
            if reason is not None:
                raise ModelPolicyError(
                    f"explicit model is ineligible: {reason}",
                    code="EXPLICIT_MODEL_INELIGIBLE",
                )
            eligible = [selected] + [
                item for item in eligible if item.qualified_name != selected.qualified_name
            ]

        if not eligible:
            raise ModelPolicyError(
                "no configured model satisfies the request profile",
                code="NO_ELIGIBLE_MODEL",
            )

        limit = 1 if not profile.allow_fallback else profile.max_candidates
        chain = tuple(eligible[:limit])
        primary = chain[0]
        fallbacks = tuple(item.qualified_name for item in chain[1:])
        estimated_costs = tuple(
            (item.qualified_name, item.estimate_cost_usd(profile)) for item in chain
        )
        payload = {
            "request_fingerprint": profile.fingerprint,
            "policy_version": self.policy_version,
            "primary_model": primary.qualified_name,
            "fallback_chain": list(fallbacks),
            "estimated_costs": [
                [name, format(cost, ".12g")] for name, cost in estimated_costs
            ],
            "excluded": [
                [item.qualified_name, item.reason] for item in excluded
            ],
            "explicit_override": explicit_override,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ModelPolicyDecision(
            request_fingerprint=profile.fingerprint,
            policy_version=self.policy_version,
            primary_model=primary.qualified_name,
            fallback_chain=fallbacks,
            estimated_costs=estimated_costs,
            excluded=tuple(excluded),
            explicit_override=explicit_override,
            fingerprint=fingerprint,
        )

    def next_fallback(
        self,
        decision: ModelPolicyDecision,
        attempts: Iterable[FallbackAttempt],
    ) -> str | None:
        history = tuple(attempts)
        if not history:
            raise ValueError("at least one attempt is required")
        latest = history[-1]
        if latest.category not in _FALLBACK_ALLOWED:
            return None
        attempted = {attempt.qualified_name for attempt in history}
        for candidate in decision.fallback_chain:
            if candidate not in attempted:
                return candidate
        return None

    def _exclusion_reason(
        self,
        profile: ModelRequestProfile,
        candidate: ModelCandidate,
    ) -> str | None:
        if not candidate.enabled:
            return "disabled"
        missing = profile.required_capabilities - candidate.capabilities
        if missing:
            return "missing_capability:" + ",".join(sorted(missing))
        if candidate.context_window_tokens < profile.required_context_tokens:
            return "context_window"
        if profile.structured_output_required and not candidate.supports_structured_output:
            return "structured_output"
        estimated_cost = candidate.estimate_cost_usd(profile)
        if (
            profile.cost_ceiling_usd is not None
            and estimated_cost > profile.cost_ceiling_usd
        ):
            return "cost_ceiling"
        return None

    @staticmethod
    def _sort_key(
        profile: ModelRequestProfile,
        candidate: ModelCandidate,
    ) -> tuple[int, float, str]:
        return (
            candidate.preference_rank,
            candidate.estimate_cost_usd(profile),
            candidate.qualified_name,
        )
