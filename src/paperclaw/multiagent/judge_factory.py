"""Composition helpers for semantic judge models."""

from __future__ import annotations

import os

from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.models.reliability import RetryPolicy


def build_judge_model_from_env() -> OpenAICompatibleModel:
    """Build a separate judge client with optional judge-specific overrides.

    The semantic gate owns its own strict total-attempt policy, so the underlying
    adapter is configured for one request attempt.  Judge settings fall back to
    the normal execution-provider settings for backward-compatible deployment.
    """

    api_key = os.getenv("PAPERCLAW_JUDGE_API_KEY") or os.getenv("PAPERCLAW_API_KEY")
    base_url = os.getenv("PAPERCLAW_JUDGE_BASE_URL") or os.getenv("PAPERCLAW_BASE_URL")
    model = os.getenv("PAPERCLAW_JUDGE_MODEL") or os.getenv("PAPERCLAW_MODEL")
    provider = (
        os.getenv("PAPERCLAW_JUDGE_PROVIDER")
        or os.getenv("PAPERCLAW_PROVIDER")
        or "openai-compatible"
    )
    missing = [
        name
        for name, value in (
            ("PAPERCLAW_JUDGE_API_KEY/PAPERCLAW_API_KEY", api_key),
            ("PAPERCLAW_JUDGE_BASE_URL/PAPERCLAW_BASE_URL", base_url),
            ("PAPERCLAW_JUDGE_MODEL/PAPERCLAW_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("missing judge model environment: " + ", ".join(missing))
    timeout = float(
        os.getenv("PAPERCLAW_JUDGE_TIMEOUT_SECONDS")
        or os.getenv("PAPERCLAW_TIMEOUT_SECONDS")
        or "120"
    )
    return OpenAICompatibleModel(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        provider=provider,
        retry_policy=RetryPolicy(max_attempts=1),
    )


__all__ = ["build_judge_model_from_env"]
