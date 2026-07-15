from __future__ import annotations

from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
import json
from typing import Any
import urllib.error

import pytest

from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.models.reliability import (
    ProviderError,
    RetryPolicy,
    normalize_provider_response,
    parse_retry_after,
)


class _Response:
    def __init__(self, data: dict[str, Any], headers: dict[str, str]) -> None:
        self._body = BytesIO(json.dumps(data).encode("utf-8"))
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _http_error(status: int, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    headers["X-Request-ID"] = "request-rate-limited"
    return urllib.error.HTTPError(
        url="https://provider.invalid/chat/completions",
        code=status,
        msg="provider error",
        hdrs=headers,
        fp=BytesIO(b'{"error":"temporary"}'),
    )


def test_retry_policy_and_retry_after_are_bounded() -> None:
    policy = RetryPolicy(
        max_attempts=4,
        base_delay_seconds=0.5,
        max_delay_seconds=2.0,
    )

    assert policy.delay_before_attempt(2) == 0.5
    assert policy.delay_before_attempt(3) == 1.0
    assert policy.delay_before_attempt(4) == 2.0
    assert policy.delay_before_attempt(2, retry_after_seconds=9.0) == 2.0
    assert parse_retry_after("1.25") == 1.25
    assert parse_retry_after(
        "Thu, 16 Jul 2026 00:00:05 GMT",
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    ) == 5.0


def test_normalizer_rejects_thinking_only_response() -> None:
    with pytest.raises(ProviderError) as caught:
        normalize_provider_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "internal reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    assert caught.value.code == "THINKING_ONLY_RESPONSE"
    assert caught.value.retriable is True


def test_adapter_retries_429_and_returns_normalized_metadata() -> None:
    attempts = [
        _http_error(429, retry_after="1"),
        _Response(
            {
                "id": "response-id",
                "choices": [
                    {
                        "message": {
                            "content": [{"type": "text", "text": "done"}],
                            "reasoning_content": "transient reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                },
            },
            {"X-Request-ID": "request-success"},
        ),
    ]
    sleeps: list[float] = []

    def urlopen(*_args: object, **_kwargs: object):
        item = attempts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    model = OpenAICompatibleModel(
        api_key="provider-secret",
        base_url="https://provider.invalid/v1",
        model="test-model",
        provider="test-provider",
        retry_policy=RetryPolicy(
            max_attempts=2,
            base_delay_seconds=0,
            max_delay_seconds=2,
        ),
        urlopen=urlopen,
        sleep=sleeps.append,
    )

    turn = model.complete("return done")

    assert turn.content == "done"
    assert turn.reasoning == "transient reasoning"
    assert turn.metadata == {
        "attempt_count": 2,
        "retry_count": 1,
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
        "finish_reason": "stop",
        "request_id": "request-success",
    }
    assert sleeps == [1.0]
    assert attempts == []


def test_adapter_does_not_retry_authentication_failure() -> None:
    attempts = [_http_error(401)]

    def urlopen(*_args: object, **_kwargs: object):
        raise attempts.pop(0)

    model = OpenAICompatibleModel(
        api_key="provider-secret",
        base_url="https://provider.invalid/v1",
        model="test-model",
        retry_policy=RetryPolicy(max_attempts=3),
        urlopen=urlopen,
        sleep=lambda _delay: pytest.fail("authentication failure must not sleep"),
    )

    with pytest.raises(ProviderError) as caught:
        model.complete("hello")

    assert caught.value.code == "AUTHENTICATION_FAILED"
    assert caught.value.retriable is False
    assert caught.value.attempt_count == 1
    assert attempts == []
