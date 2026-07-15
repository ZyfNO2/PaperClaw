"""Provider reliability primitives independent from any concrete SDK.

The module intentionally owns retry/error/response normalization only. It does
not know about QueryEngine, SessionService, Trace storage, prompts, tools, or
provider-specific client libraries.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from typing import Any, Mapping

RETRIABLE_HTTP_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy for one provider completion request.

    ``max_attempts`` includes the initial request. The default of one preserves
    the pre-v0.07.1 behavior until the user explicitly enables retries.
    """

    max_attempts: int = 1
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    respect_retry_after: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        for name, value in (
            ("base_delay_seconds", self.base_delay_seconds),
            ("max_delay_seconds", self.max_delay_seconds),
        ):
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError(
                "max_delay_seconds must be greater than or equal to "
                "base_delay_seconds"
            )

    def delay_before_attempt(
        self,
        next_attempt: int,
        *,
        retry_after_seconds: float | None = None,
    ) -> float:
        """Return the bounded delay before ``next_attempt`` (2-based or later)."""

        if next_attempt <= 1:
            return 0.0
        exponential = self.base_delay_seconds * (2 ** (next_attempt - 2))
        delay = min(self.max_delay_seconds, exponential)
        if (
            self.respect_retry_after
            and retry_after_seconds is not None
            and math.isfinite(retry_after_seconds)
            and retry_after_seconds >= 0
        ):
            delay = max(delay, retry_after_seconds)
        return min(self.max_delay_seconds, delay)


class ProviderError(RuntimeError):
    """Structured, sanitized failure crossing the model adapter boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retriable: bool,
        status_code: int | None = None,
        request_id: str | None = None,
        attempt_count: int = 1,
        retry_after_seconds: float | None = None,
        response_excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retriable = retriable
        self.status_code = status_code
        self.request_id = request_id
        self.attempt_count = attempt_count
        self.retry_after_seconds = retry_after_seconds
        self.response_excerpt = response_excerpt

    @property
    def retry_count(self) -> int:
        return max(0, self.attempt_count - 1)

    def with_attempt(self, attempt_count: int) -> "ProviderError":
        return ProviderError(
            str(self),
            code=self.code,
            retriable=self.retriable,
            status_code=self.status_code,
            request_id=self.request_id,
            attempt_count=attempt_count,
            retry_after_seconds=self.retry_after_seconds,
            response_excerpt=self.response_excerpt,
        )

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider_error_code": self.code,
            "retriable": self.retriable,
            "attempt_count": self.attempt_count,
            "retry_count": self.retry_count,
        }
        if self.status_code is not None:
            metadata["status_code"] = self.status_code
        if self.request_id:
            metadata["request_id"] = self.request_id
        if self.retry_after_seconds is not None:
            metadata["retry_after_seconds"] = self.retry_after_seconds
        return metadata


@dataclass(frozen=True)
class NormalizedProviderResponse:
    content: str
    reasoning: str
    finish_reason: str | None
    request_id: str | None
    usage: dict[str, int]


def classify_http_error(status_code: int) -> tuple[str, bool]:
    if status_code == 400:
        return "INVALID_REQUEST", False
    if status_code == 401:
        return "AUTHENTICATION_FAILED", False
    if status_code == 403:
        return "PERMISSION_DENIED", False
    if status_code == 404:
        return "MODEL_OR_ENDPOINT_NOT_FOUND", False
    if status_code == 413:
        return "REQUEST_TOO_LARGE", False
    if status_code == 429:
        return "RATE_LIMITED", True
    if status_code in RETRIABLE_HTTP_STATUSES:
        return "PROVIDER_TEMPORARILY_UNAVAILABLE", True
    if 500 <= status_code <= 599:
        return "PROVIDER_SERVER_ERROR", True
    return "PROVIDER_HTTP_ERROR", False


def parse_retry_after(
    value: str | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Parse Retry-After seconds or an RFC 7231 HTTP date."""

    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        seconds = float(normalized)
    except ValueError:
        seconds = None
    if seconds is not None:
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
        return None
    try:
        retry_at = parsedate_to_datetime(normalized)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - reference).total_seconds())


def extract_request_id(headers: Mapping[str, Any]) -> str | None:
    lowered = {str(key).lower(): value for key, value in headers.items()}
    for key in (
        "x-request-id",
        "request-id",
        "mistral-request-id",
        "x-ms-request-id",
    ):
        value = lowered.get(key)
        if value is not None:
            normalized = str(value).strip()
            if normalized:
                return normalized[:200]
    return None


def normalize_provider_response(
    data: Any,
    *,
    headers: Mapping[str, Any] | None = None,
) -> NormalizedProviderResponse:
    """Normalize OpenAI-compatible response variants without exposing prompts."""

    if not isinstance(data, Mapping):
        raise ProviderError(
            "provider returned a non-object response",
            code="INVALID_PROVIDER_RESPONSE",
            retriable=True,
        )
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError(
            "provider response does not contain choices",
            code="INVALID_PROVIDER_RESPONSE",
            retriable=True,
        )
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ProviderError(
            "provider choice is not an object",
            code="INVALID_PROVIDER_RESPONSE",
            retriable=True,
        )
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ProviderError(
            "provider choice does not contain a message",
            code="INVALID_PROVIDER_RESPONSE",
            retriable=True,
        )

    content = _normalize_text_content(message.get("content"))
    reasoning = _first_text(
        message.get("reasoning_content"),
        message.get("reasoning"),
        message.get("thinking"),
    )
    if not content:
        if reasoning:
            raise ProviderError(
                "provider returned reasoning without final content",
                code="THINKING_ONLY_RESPONSE",
                retriable=True,
            )
        raise ProviderError(
            "provider returned an empty message",
            code="EMPTY_PROVIDER_RESPONSE",
            retriable=True,
        )

    finish_reason = choice.get("finish_reason")
    normalized_finish_reason = (
        str(finish_reason).strip()[:100]
        if finish_reason is not None and str(finish_reason).strip()
        else None
    )
    usage = _normalize_usage(data.get("usage"))
    request_id = extract_request_id(headers or {})
    if request_id is None:
        for key in ("id", "request_id", "requestId"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                request_id = value.strip()[:200]
                break
    return NormalizedProviderResponse(
        content=content,
        reasoning=reasoning,
        finish_reason=normalized_finish_reason,
        request_id=request_id,
        usage=usage,
    )


def _normalize_text_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    fragments: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, Mapping):
            text_value = item.get("text")
            text = text_value.strip() if isinstance(text_value, str) else ""
        else:
            text = ""
        if text:
            fragments.append(text)
    return "\n".join(fragments).strip()


def _first_text(*values: Any) -> str:
    for value in values:
        normalized = _normalize_text_content(value)
        if normalized:
            return normalized
    return ""


def _normalize_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    aliases = {
        "prompt_tokens": "input_tokens",
        "input_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
        "output_tokens": "output_tokens",
        "total_tokens": "total_tokens",
    }
    usage: dict[str, int] = {}
    for source, target in aliases.items():
        raw = value.get(source)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)) and raw >= 0:
            usage[target] = int(raw)
    return usage
