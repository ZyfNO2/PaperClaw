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
    classify_http_error,
    normalize_provider_response,
    parse_retry_after,
)


@pytest.mark.parametrize(
    ("status", "code", "retriable"),
    [
        (400, "INVALID_REQUEST", False),
        (401, "AUTHENTICATION_FAILED", False),
        (403, "PERMISSION_DENIED", False),
        (404, "MODEL_OR_ENDPOINT_NOT_FOUND", False),
        (408, "PROVIDER_TEMPORARILY_UNAVAILABLE", True),
        (409, "PROVIDER_TEMPORARILY_UNAVAILABLE", True),
        (429, "RATE_LIMITED", True),
        (500, "PROVIDER_TEMPORARILY_UNAVAILABLE", True),
        (501, "PROVIDER_SERVER_ERROR", True),
        (502, "PROVIDER_TEMPORARILY_UNAVAILABLE", True),
        (503, "PROVIDER_TEMPORARILY_UNAVAILABLE", True),
        (504, "PROVIDER_TEMPORARILY_UNAVAILABLE", True),
    ],
)
def test_provider_http_error_matrix(
    status: int, code: str, retriable: bool
) -> None:
    assert classify_http_error(status) == (code, retriable)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": -1},
        {"max_attempts": True},
        {"max_attempts": 11},
        {"max_attempts": 100},
        {"max_attempts": 1.5},
        {"max_attempts": "2"},
        {"base_delay_seconds": -1},
        {"max_delay_seconds": -1},
        {"base_delay_seconds": float("inf")},
        {"base_delay_seconds": 2, "max_delay_seconds": 1},
    ],
)
def test_retry_policy_rejects_unsafe_configuration(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({}, "INVALID_PROVIDER_RESPONSE"),
        ({"choices": []}, "INVALID_PROVIDER_RESPONSE"),
        ({"choices": [{}]}, "INVALID_PROVIDER_RESPONSE"),
        ({"choices": [{"message": None}]}, "INVALID_PROVIDER_RESPONSE"),
        ({"choices": [{"message": {"content": ""}}]}, "EMPTY_PROVIDER_RESPONSE"),
    ],
)
def test_normalizer_rejects_malformed_provider_shapes(
    payload: dict[str, Any], code: str
) -> None:
    with pytest.raises(ProviderError) as caught:
        normalize_provider_response(payload)
    assert caught.value.code == code


def test_invalid_retry_after_and_usage_types_are_ignored() -> None:
    assert parse_retry_after("not-a-delay") is None
    assert parse_retry_after("-1") is None
    normalized = normalize_provider_response(
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": "wrong type",
        }
    )
    assert normalized.usage == {}


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
