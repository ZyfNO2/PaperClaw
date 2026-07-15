"""Guarded external HTTPS exporter for already-redacted TraceEvent data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import ipaddress
import json
import math
from typing import Any, Protocol
import urllib.error
import urllib.request
from urllib.parse import urlparse

from paperclaw.trace import TraceReader

Urlopen = Callable[..., Any]


class ExternalExportError(RuntimeError):
    """Sanitized external export failure."""


@dataclass(frozen=True)
class ExternalExportPolicy:
    enabled: bool = False
    allowed_hosts: tuple[str, ...] = ()
    timeout_seconds: float = 10.0
    max_events: int = 10_000
    max_payload_bytes: int = 5_000_000

    def __post_init__(self) -> None:
        if not self.allowed_hosts and self.enabled:
            raise ValueError("enabled external export requires allowed_hosts")
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or self.timeout_seconds > 120
        ):
            raise ValueError("timeout_seconds must be in (0, 120]")
        for name, value in (
            ("max_events", self.max_events),
            ("max_payload_bytes", self.max_payload_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class ExternalExportSummary:
    exporter: str
    run_id: str
    endpoint_host: str
    event_count: int
    payload_bytes: int
    status_code: int
    request_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TraceExporter(Protocol):
    def export_run(
        self,
        reader: TraceReader,
        run_id: str,
        *,
        require_terminal: bool = True,
    ) -> ExternalExportSummary: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpTraceExporter:
    """POST a bounded TraceEvent envelope to one explicitly allowed HTTPS host."""

    def __init__(
        self,
        endpoint: str,
        *,
        policy: ExternalExportPolicy,
        bearer_token: str | None = None,
        urlopen: Urlopen | None = None,
    ) -> None:
        self._policy = policy
        self._endpoint = endpoint
        self._host = _validate_endpoint(endpoint, policy)
        self._bearer_token = bearer_token or None
        self._urlopen = urlopen or urllib.request.build_opener(
            _NoRedirectHandler()
        ).open

    def export_run(
        self,
        reader: TraceReader,
        run_id: str,
        *,
        require_terminal: bool = True,
    ) -> ExternalExportSummary:
        if not self._policy.enabled:
            raise ExternalExportError("external export is disabled by policy")
        events = reader.get_run_trace(run_id, require_terminal=require_terminal)
        if len(events) > self._policy.max_events:
            raise ExternalExportError(
                f"trace contains {len(events)} events; limit is "
                f"{self._policy.max_events}"
            )
        envelope = {
            "schema_version": 1,
            "exporter": "paperclaw-http-json-v1",
            "run_id": run_id,
            "event_count": len(events),
            "events": [event.to_dict() for event in events],
        }
        payload = json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(payload) > self._policy.max_payload_bytes:
            raise ExternalExportError(
                f"trace payload is {len(payload)} bytes; limit is "
                f"{self._policy.max_payload_bytes}"
            )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PaperClaw-Trace-Exporter/1",
        }
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        request = urllib.request.Request(
            self._endpoint,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with self._urlopen(
                request,
                timeout=self._policy.timeout_seconds,
            ) as response:
                status = int(getattr(response, "status", 200))
                response_headers = {
                    str(key).lower(): str(value)
                    for key, value in response.headers.items()
                }
        except urllib.error.HTTPError as exc:
            raise ExternalExportError(
                f"external export failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ExternalExportError(
                "external export failed to connect or timed out"
            ) from exc
        if status < 200 or status >= 300:
            raise ExternalExportError(
                f"external export returned unexpected HTTP {status}"
            )
        request_id = None
        for key in ("x-request-id", "request-id"):
            value = response_headers.get(key)
            if value:
                request_id = value[:200]
                break
        return ExternalExportSummary(
            exporter="paperclaw-http-json-v1",
            run_id=run_id,
            endpoint_host=self._host,
            event_count=len(events),
            payload_bytes=len(payload),
            status_code=status,
            request_id=request_id,
        )


def _validate_endpoint(endpoint: str, policy: ExternalExportPolicy) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("external export endpoint must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("external export endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("external export endpoint must not contain query or fragment")
    host = parsed.hostname.lower().rstrip(".")
    allowed = {item.lower().rstrip(".") for item in policy.allowed_hosts}
    if host not in allowed:
        raise ValueError(f"endpoint host is not allowlisted: {host}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP-literal exporter endpoints are not allowed")
    return host
