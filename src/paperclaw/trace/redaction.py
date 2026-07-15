"""Deterministic redaction and JSON-safety for trace payloads."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

_REDACTED = "<REDACTED>"
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "access_token",
        "refresh_token",
        "bearer_token",
        "private_key",
    }
)
_SENSITIVE_CONTENT_KEYS = frozenset(
    {
        "prompt",
        "system_prompt",
        "user_prompt",
        "messages",
        "reasoning",
        "reasoning_content",
        "thinking",
        "chain_of_thought",
        "tool_output",
        "stdout",
        "stderr",
        "file_content",
        "raw_input",
        "request_body",
        "response_body",
    }
)
_HOME_PATTERNS = (
    re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:\\Users\\[^\\/\s]+"),
    re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users)/[^/\s]+"),
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]{8,}")


class TraceRedactor:
    """Convert arbitrary runtime payloads into bounded, JSON-safe data.

    Redaction is intentionally conservative and deterministic.  Callers may
    provide exact secret values (for example the active provider key) so those
    values are removed even when they appear inside exception messages rather
    than under a well-known key.
    """

    def __init__(
        self,
        *,
        secret_values: Iterable[str] = (),
        max_string_chars: int = 800,
        max_collection_items: int = 100,
        max_depth: int = 8,
    ) -> None:
        if max_string_chars <= 0:
            raise ValueError("max_string_chars must be positive")
        if max_collection_items <= 0:
            raise ValueError("max_collection_items must be positive")
        if max_depth <= 0:
            raise ValueError("max_depth must be positive")
        self._secret_values = tuple(
            sorted(
                {value for value in secret_values if value},
                key=len,
                reverse=True,
            )
        )
        self._max_string_chars = max_string_chars
        self._max_collection_items = max_collection_items
        self._max_depth = max_depth

    def redact_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            str(key): self._redact_value(value, key=str(key), depth=0)
            for key, value in payload.items()
        }

    def redact_text(self, value: str) -> str:
        redacted = value
        for secret in self._secret_values:
            redacted = redacted.replace(secret, _REDACTED)
        redacted = _BEARER_PATTERN.sub("Bearer <REDACTED>", redacted)
        for pattern in _HOME_PATTERNS:
            redacted = pattern.sub("<HOME>", redacted)
        if len(redacted) <= self._max_string_chars:
            return redacted
        digest = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        preview = redacted[: self._max_string_chars]
        return (
            f"{preview}…<truncated chars={len(redacted)} "
            f"sha256={digest}>"
        )

    def _redact_value(self, value: Any, *, key: str, depth: int) -> Any:
        normalized_key = key.strip().lower().replace("-", "_")
        if normalized_key in _SECRET_KEYS or normalized_key.endswith("_api_key"):
            return _REDACTED
        if normalized_key.endswith("_token") and normalized_key not in {
            "input_token",
            "output_token",
        }:
            return _REDACTED
        if normalized_key in _SENSITIVE_CONTENT_KEYS:
            return _summarize_sensitive_content(value)
        if depth >= self._max_depth:
            return "<MAX_DEPTH>"
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            return str(value)
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Path):
            return self.redact_text(str(value))
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, bytes):
            return {
                "type": "bytes",
                "length": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
            }
        if is_dataclass(value):
            return self._redact_value(asdict(value), key=key, depth=depth + 1)
        if isinstance(value, Mapping):
            items = list(value.items())
            result = {
                str(child_key): self._redact_value(
                    child_value,
                    key=str(child_key),
                    depth=depth + 1,
                )
                for child_key, child_value in items[: self._max_collection_items]
            }
            if len(items) > self._max_collection_items:
                result["__truncated_items__"] = len(items) - self._max_collection_items
            return result
        if isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
            result = [
                self._redact_value(item, key=key, depth=depth + 1)
                for item in items[: self._max_collection_items]
            ]
            if len(items) > self._max_collection_items:
                result.append(
                    {"__truncated_items__": len(items) - self._max_collection_items}
                )
            return result
        return self.redact_text(repr(value))


def _summarize_sensitive_content(value: Any) -> dict[str, Any]:
    """Return a deterministic non-preview summary for sensitive full text."""

    if isinstance(value, bytes):
        encoded = value
        length = len(value)
        unit = "bytes"
    else:
        text = value if isinstance(value, str) else repr(value)
        encoded = text.encode("utf-8", errors="replace")
        length = len(text)
        unit = "chars"
    return {
        "redacted": True,
        "length": length,
        "length_unit": unit,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
