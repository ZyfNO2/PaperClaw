from __future__ import annotations

from email.message import Message
import json

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
