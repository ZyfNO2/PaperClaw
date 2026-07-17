"""Frozen contracts for the v0.10 static Model Policy foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
POLICY_VERSION = "paperclaw.model-policy.v0.10.0"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must match {_IDENTIFIER.pattern}")


def _require_non_negative_finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


class ModelPolicyError(RuntimeError):
    """Structured fail-closed routing error."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class ModelFailureCategory(str, Enum):
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_OVERFLOW = "context_overflow"
    STRUCTURED_OUTPUT = "structured_output"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModelRequestProfile:
    """Structured facts allowed to influence static model selection."""

    required_capabilities: frozenset[str] = frozenset()
    estimated_input_tokens: int = 0
    output_reserve_tokens: int = 0
    structured_output_required: bool = False
    cost_ceiling_usd: float | None = None
    explicit_model: str | None = None
    max_candidates: int = 3
    allow_fallback: bool = True

    def __post_init__(self) -> None:
        if self.estimated_input_tokens < 0 or self.output_reserve_tokens < 0:
            raise ValueError("token estimates must be non-negative")
        if self.cost_ceiling_usd is not None:
            _require_non_negative_finite("cost_ceiling_usd", self.cost_ceiling_usd)
        if self.explicit_model is not None:
            _require_identifier("explicit_model", self.explicit_model)
        if self.max_candidates < 1 or self.max_candidates > 20:
            raise ValueError("max_candidates must be in [1, 20]")
        for capability in self.required_capabilities:
            _require_identifier("required capability", capability)

    @property
    def required_context_tokens(self) -> int:
        return self.estimated_input_tokens + self.output_reserve_tokens

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "required_capabilities": sorted(self.required_capabilities),
                "estimated_input_tokens": self.estimated_input_tokens,
                "output_reserve_tokens": self.output_reserve_tokens,
                "structured_output_required": self.structured_output_required,
                "cost_ceiling_usd": self.cost_ceiling_usd,
                "explicit_model": self.explicit_model,
                "max_candidates": self.max_candidates,
                "allow_fallback": self.allow_fallback,
            }
        )


@dataclass(frozen=True)
class ModelCandidate:
    provider_id: str
    model_id: str
    capabilities: frozenset[str]
    context_window_tokens: int
    supports_structured_output: bool
    input_cost_usd_per_million: float
    output_cost_usd_per_million: float
    preference_rank: int = 100
    enabled: bool = True

    def __post_init__(self) -> None:
        _require_identifier("provider_id", self.provider_id)
        _require_identifier("model_id", self.model_id)
        if self.context_window_tokens < 1:
            raise ValueError("context_window_tokens must be positive")
        if self.preference_rank < 0:
            raise ValueError("preference_rank must be non-negative")
        _require_non_negative_finite(
            "input_cost_usd_per_million", self.input_cost_usd_per_million
        )
        _require_non_negative_finite(
            "output_cost_usd_per_million", self.output_cost_usd_per_million
        )
        for capability in self.capabilities:
            _require_identifier("capability", capability)

    @property
    def qualified_name(self) -> str:
        return f"{self.provider_id}:{self.model_id}"

    def estimate_cost_usd(self, profile: ModelRequestProfile) -> float:
        input_cost = (
            profile.estimated_input_tokens
            * float(self.input_cost_usd_per_million)
            / 1_000_000
        )
        output_cost = (
            profile.output_reserve_tokens
            * float(self.output_cost_usd_per_million)
            / 1_000_000
        )
        return input_cost + output_cost

    def descriptor(self) -> dict[str, Any]:
        return {
            "qualified_name": self.qualified_name,
            "capabilities": sorted(self.capabilities),
            "context_window_tokens": self.context_window_tokens,
            "supports_structured_output": self.supports_structured_output,
            "input_cost_usd_per_million": self.input_cost_usd_per_million,
            "output_cost_usd_per_million": self.output_cost_usd_per_million,
            "preference_rank": self.preference_rank,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class ModelExclusion:
    qualified_name: str
    reason: str


@dataclass(frozen=True)
class ModelPolicyDecision:
    request_fingerprint: str
    policy_version: str
    primary_model: str
    fallback_chain: tuple[str, ...]
    estimated_costs: tuple[tuple[str, float], ...]
    excluded: tuple[ModelExclusion, ...]
    explicit_override: bool
    fingerprint: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "request_fingerprint": self.request_fingerprint,
            "policy_version": self.policy_version,
            "primary_model": self.primary_model,
            "fallback_chain": list(self.fallback_chain),
            "estimated_costs": dict(self.estimated_costs),
            "excluded": [asdict(item) for item in self.excluded],
            "explicit_override": self.explicit_override,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class FallbackAttempt:
    qualified_name: str
    category: ModelFailureCategory
    error_code: str

    def __post_init__(self) -> None:
        _require_identifier("qualified_name", self.qualified_name)
        _require_identifier("error_code", self.error_code)
