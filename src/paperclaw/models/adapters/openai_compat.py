from __future__ import annotations

from collections.abc import Callable
import json
import os
import platform
import socket
import time
from typing import Any
import urllib.error
import urllib.request

from paperclaw.models.base import ModelTurn
from paperclaw.models.reliability import (
    ProviderError,
    RetryPolicy,
    classify_http_error,
    extract_request_id,
    normalize_provider_response,
    parse_retry_after,
)

Urlopen = Callable[..., Any]
Sleep = Callable[[float], None]


class OpenAICompatibleModel:
    """Small stdlib adapter for an OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60,
        provider: str = "openai-compatible",
        retry_policy: RetryPolicy | None = None,
        urlopen: Urlopen | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.provider = provider.strip() or "openai-compatible"
        self.retry_policy = retry_policy or RetryPolicy()
        self._urlopen = urlopen or urllib.request.urlopen
        self._sleep = sleep or time.sleep

    @classmethod
    def from_env(cls) -> "OpenAICompatibleModel":
        required = {
            name: os.getenv(name)
            for name in (
                "PAPERCLAW_API_KEY",
                "PAPERCLAW_BASE_URL",
                "PAPERCLAW_MODEL",
            )
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"missing environment variables: {', '.join(missing)}")
        timeout = float(os.getenv("PAPERCLAW_TIMEOUT_SECONDS", "120"))
        provider = os.getenv("PAPERCLAW_PROVIDER", "openai-compatible")
        retry_policy = RetryPolicy(
            max_attempts=int(os.getenv("PAPERCLAW_PROVIDER_MAX_ATTEMPTS", "1")),
            base_delay_seconds=float(
                os.getenv("PAPERCLAW_PROVIDER_BACKOFF_SECONDS", "0.5")
            ),
            max_delay_seconds=float(
                os.getenv("PAPERCLAW_PROVIDER_MAX_BACKOFF_SECONDS", "8")
            ),
            respect_retry_after=_env_bool(
                "PAPERCLAW_PROVIDER_RESPECT_RETRY_AFTER",
                default=True,
            ),
        )
        return cls(
            api_key=required["PAPERCLAW_API_KEY"],
            base_url=required["PAPERCLAW_BASE_URL"],
            model=required["PAPERCLAW_MODEL"],
            timeout=timeout,
            provider=provider,
            retry_policy=retry_policy,
        )

    def complete(self, prompt: str) -> ModelTurn:
        last_error: ProviderError | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                data, headers = self._request_once(prompt)
                normalized = normalize_provider_response(data, headers=headers)
                metadata: dict[str, Any] = {
                    "attempt_count": attempt,
                    "retry_count": attempt - 1,
                    **normalized.usage,
                }
                if normalized.finish_reason:
                    metadata["finish_reason"] = normalized.finish_reason
                if normalized.request_id:
                    metadata["request_id"] = normalized.request_id
                return ModelTurn(
                    content=normalized.content,
                    reasoning=normalized.reasoning,
                    metadata=metadata,
                )
            except ProviderError as exc:
                request_id = exc.request_id
                if request_id is None and "headers" in locals():
                    request_id = extract_request_id(headers)
                last_error = ProviderError(
                    str(exc),
                    code=exc.code,
                    retriable=exc.retriable,
                    status_code=exc.status_code,
                    request_id=request_id,
                    attempt_count=attempt,
                    retry_after_seconds=exc.retry_after_seconds,
                    response_excerpt=exc.response_excerpt,
                )
                if not last_error.retriable or attempt >= self.retry_policy.max_attempts:
                    raise last_error from exc
                delay = self.retry_policy.delay_before_attempt(
                    attempt + 1,
                    retry_after_seconds=last_error.retry_after_seconds,
                )
                if delay > 0:
                    self._sleep(delay)
        assert last_error is not None
        raise last_error

    def _request_once(self, prompt: str) -> tuple[Any, dict[str, str]]:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Some compatible gateways reject stdlib urllib traffic unless
                # a normal User-Agent is present.
                "User-Agent": (
                    f"PaperClaw/0.0.1 "
                    f"({platform.system()} {platform.release()})"
                ),
            },
            method="POST",
        )
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                headers = {
                    str(key): str(value)
                    for key, value in response.headers.items()
                }
                try:
                    data = json.load(response)
                except (TypeError, ValueError) as exc:
                    raise ProviderError(
                        "provider returned invalid JSON",
                        code="INVALID_PROVIDER_RESPONSE",
                        retriable=True,
                        request_id=extract_request_id(headers),
                    ) from exc
                return data, headers
        except urllib.error.HTTPError as exc:
            headers = {
                str(key): str(value)
                for key, value in (exc.headers.items() if exc.headers else [])
            }
            raw_body = exc.read().decode("utf-8", errors="replace")
            excerpt = _sanitize_excerpt(raw_body, self.api_key)
            code, retriable = classify_http_error(exc.code)
            raise ProviderError(
                f"provider request failed with HTTP {exc.code} ({code})",
                code=code,
                retriable=retriable,
                status_code=exc.code,
                request_id=extract_request_id(headers),
                retry_after_seconds=parse_retry_after(
                    headers.get("Retry-After") or headers.get("retry-after")
                ),
                response_excerpt=excerpt,
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise ProviderError(
                "provider request timed out or failed to connect",
                code="PROVIDER_NETWORK_ERROR",
                retriable=True,
            ) from exc


def _sanitize_excerpt(value: str, api_key: str) -> str:
    sanitized = value.replace(api_key, "<REDACTED>") if api_key else value
    return sanitized[:500]


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")
