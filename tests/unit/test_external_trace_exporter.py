from __future__ import annotations

from email.message import Message
import json
from io import BytesIO
import urllib.error

import pytest

from paperclaw.exporters import (
    ExternalExportError,
    ExternalExportPolicy,
    HttpTraceExporter,
)
from paperclaw.trace import TraceEvent


class _Reader:
    def get_run_trace(self, run_id: str, **_kwargs):
        assert run_id == "run-export"
        return (
            TraceEvent(
                event_id="evt-1",
                sequence=1,
                occurred_at="2026-07-16T00:00:00+00:00",
                conversation_id="conv-export",
                run_id="run-export",
                event_type="run.completed",
                component="harness",
                status="completed",
                payload={"authorization": "<REDACTED>"},
            ),
        )

    def iter_run_trace(self, run_id: str, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


class _Response:
    status = 202

    def __init__(self) -> None:
        self.headers = Message()
        self.headers["X-Request-ID"] = "collector-request"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_http_exporter_requires_explicit_policy_and_allowlist() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        HttpTraceExporter(
            "http://collector.example/traces",
            policy=ExternalExportPolicy(
                enabled=True,
                allowed_hosts=("collector.example",),
            ),
        )

    with pytest.raises(ValueError, match="allowlisted"):
        HttpTraceExporter(
            "https://other.example/traces",
            policy=ExternalExportPolicy(
                enabled=True,
                allowed_hosts=("collector.example",),
            ),
        )


def test_http_exporter_posts_bounded_redacted_envelope() -> None:
    captured = {}

    def urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    exporter = HttpTraceExporter(
        "https://collector.example/v1/traces",
        policy=ExternalExportPolicy(
            enabled=True,
            allowed_hosts=("collector.example",),
            timeout_seconds=3,
        ),
        bearer_token="export-token",
        urlopen=urlopen,
    )

    summary = exporter.export_run(_Reader(), "run-export")
    request = captured["request"]
    envelope = json.loads(request.data.decode("utf-8"))

    assert captured["timeout"] == 3
    assert request.get_header("Authorization") == "Bearer export-token"
    assert "export-token" not in request.data.decode("utf-8")
    assert envelope["event_count"] == 1
    assert envelope["events"][0]["payload"]["authorization"] == "<REDACTED>"
    assert summary.status_code == 202
    assert summary.request_id == "collector-request"
    assert summary.endpoint_host == "collector.example"


def test_http_exporter_is_disabled_by_default() -> None:
    exporter = HttpTraceExporter(
        "https://collector.example/traces",
        policy=ExternalExportPolicy(
            allowed_hosts=("collector.example",),
        ),
        urlopen=lambda *_args, **_kwargs: pytest.fail("network must not run"),
    )

    with pytest.raises(ExternalExportError, match="disabled"):
        exporter.export_run(_Reader(), "run-export")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://collector.example/traces",
        "https://user:pass@collector.example/traces",
        "https://collector.example/traces?secret=value",
        "https://collector.example/traces#fragment",
        "https://127.0.0.1/traces",
        "https://10.0.0.1/traces",
        "https://192.168.1.1/traces",
    ],
)
def test_http_exporter_rejects_unsafe_endpoints(endpoint: str) -> None:
    host = endpoint.split("//", 1)[-1].split("/", 1)[0].split("@")[-1]
    with pytest.raises(ValueError):
        HttpTraceExporter(
            endpoint,
            policy=ExternalExportPolicy(enabled=True, allowed_hosts=(host,)),
        )


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_http_exporter_sanitizes_collector_http_errors(status: int) -> None:
    def urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://collector.example/traces",
            status,
            "secret response body",
            Message(),
            BytesIO(b"collector-secret"),
        )

    exporter = HttpTraceExporter(
        "https://collector.example/traces",
        policy=ExternalExportPolicy(
            enabled=True, allowed_hosts=("collector.example",)
        ),
        bearer_token="export-secret",
        urlopen=urlopen,
    )
    with pytest.raises(ExternalExportError, match=f"HTTP {status}") as caught:
        exporter.export_run(_Reader(), "run-export")
    assert "secret" not in str(caught.value)


def test_http_exporter_enforces_event_and_payload_limits() -> None:
    for policy, match in (
        (
            ExternalExportPolicy(
                enabled=True,
                allowed_hosts=("collector.example",),
                max_events=1,
            ),
            "events",
        ),
        (
            ExternalExportPolicy(
                enabled=True,
                allowed_hosts=("collector.example",),
                max_payload_bytes=10,
            ),
            "payload",
        ),
    ):
        reader = _Reader()
        if match == "events":
            original = reader.get_run_trace
            reader.get_run_trace = lambda run_id, **kwargs: original(  # type: ignore[method-assign]
                run_id, **kwargs
            ) * 2
        exporter = HttpTraceExporter(
            "https://collector.example/traces",
            policy=policy,
            urlopen=lambda *_args, **_kwargs: pytest.fail("network must not run"),
        )
        with pytest.raises(ExternalExportError, match=match):
            exporter.export_run(reader, "run-export")
