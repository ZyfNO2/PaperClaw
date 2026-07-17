from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import re
from typing import Mapping
from urllib.parse import urlparse

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


@dataclass(frozen=True)
class CredentialRef:
    """Reference to a secret source. The secret value is never serialized."""

    env_var: str

    def __post_init__(self) -> None:
        if not self.env_var or not self.env_var.replace("_", "").isalnum():
            raise ValueError("env_var must be a non-empty environment variable name")

    def resolve(self, environ: Mapping[str, str] | None = None) -> str:
        source = os.environ if environ is None else environ
        value = source.get(self.env_var, "")
        if not value:
            raise RuntimeError(f"missing credential environment variable: {self.env_var}")
        return value


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    base_url: str
    credential: CredentialRef
    timeout_seconds: float = 120.0
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.provider_id) is None:
            raise ValueError("invalid provider_id")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be in [1, 10]")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "base_url": self.base_url.rstrip("/"),
            "credential_env_var": self.credential.env_var,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
        }


@dataclass(frozen=True)
class ModelConfig:
    provider_id: str
    model_id: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    context_window_tokens: int = 128_000
    supports_structured_output: bool = False
    input_cost_usd_per_million: float = 0.0
    output_cost_usd_per_million: float = 0.0
    preference_rank: int = 100
    enabled: bool = True

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.provider_id) is None:
            raise ValueError("invalid provider_id")
        if _IDENTIFIER.fullmatch(self.model_id) is None:
            raise ValueError("invalid model_id")
        if self.context_window_tokens < 1:
            raise ValueError("context_window_tokens must be positive")
        if self.preference_rank < 0:
            raise ValueError("preference_rank must be non-negative")
        if self.input_cost_usd_per_million < 0 or self.output_cost_usd_per_million < 0:
            raise ValueError("model costs must be non-negative")

    @property
    def qualified_name(self) -> str:
        return f"{self.provider_id}:{self.model_id}"


@dataclass(frozen=True)
class ProviderCatalog:
    providers: tuple[ProviderConfig, ...]
    models: tuple[ModelConfig, ...]

    def __post_init__(self) -> None:
        provider_ids = [item.provider_id for item in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider_id values must be unique")
        known = set(provider_ids)
        qualified = [item.qualified_name for item in self.models]
        if len(qualified) != len(set(qualified)):
            raise ValueError("qualified model names must be unique")
        missing = sorted({item.provider_id for item in self.models} - known)
        if missing:
            raise ValueError(f"models reference unknown providers: {', '.join(missing)}")

    def to_public_json(self) -> str:
        payload = {
            "providers": [item.to_public_dict() for item in self.providers],
            "models": [
                {
                    **asdict(item),
                    "capabilities": sorted(item.capabilities),
                    "qualified_name": item.qualified_name,
                }
                for item in self.models
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
