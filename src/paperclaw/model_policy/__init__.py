"""PaperClaw v0.10 static Model Policy foundation."""

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
from paperclaw.model_policy.router import StaticModelPolicyRouter

__all__ = [
    "FallbackAttempt",
    "ModelCandidate",
    "ModelExclusion",
    "ModelFailureCategory",
    "ModelPolicyDecision",
    "ModelPolicyError",
    "ModelRequestProfile",
    "POLICY_VERSION",
    "StaticModelPolicyRouter",
]
