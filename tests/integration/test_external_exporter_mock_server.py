from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from threading import Thread
import time
from typing import Iterator
import urllib.request

import pytest

from paperclaw.exporters import (
    ExternalExportError,
    ExternalExportPolicy,
    HttpTraceExporter,
)
from paperclaw.trace import TraceEvent


class _Reader:
    def __init__(self, events: tuple[TraceEvent, ...]) -> None:
        self._events = events

    def get_run_trace(self, run_id: str, **_kwargs) -> tuple[TraceEvent, ...]:
        assert run_id == "run-export-server"
        return self._events

    def iter_run_trace(self, run_id: str, **kwargs):
        yield from self.get_run_trace(run_id, **kwargs)


class _CollectorHandler(BaseHTTPRequestHandler):
    status_code = 200
    delay_seconds = 0.0
    response_body = b'{"ok":true}'
    received: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).received.append(
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )
        if type(self).delay_seconds:
            time.sleep(type(self).delay_seconds)
        self.send_response(type(self).status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Request-ID", "mock-collector-request")
        self.end_headers()
        try:
            self.wfile.write(type(self).response_body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def _mock_collector(
    *,
    status_code: int = 200,
    delay_seconds: float = 0.0,
    response_body: bytes = b'{"ok":true}',
) -> Iterator[tuple[int, type[_CollectorHandler]]]:
    handler = type(
        "ConfiguredCollectorHandler",
        (_CollectorHandler,),
        {
            "status_code": status_code,
            "delay_seconds": delay_seconds,
            "response_body": response_body,
            "received": [],
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = int(server.server_address[1])
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _route_to_localhost(port: int):
    def open_local(request: urllib.request.Request, *, timeout: float):
        local_request = urllib.request.Request(
            f"http://127.0.0.1:{port}{request.selector}",
            data=request.data,
            headers=dict(request.header_items()),
            method=request.get_method(),
        )
        return urllib.request.urlopen(local_request, timeout=timeout)

    return open_local


def _events(secret: str = "trace-secret-value") -> tuple[TraceEvent, ...]:
    return (
        TraceEvent(
            event_id="evt-1",
            sequence=1,
            occurred_at="2026-07-16T00:00:01+00:00",
            conversation_id="conv-export-server",
            run_id="run-export-server",
            event_type="run.started",
            component="harness",
            status="started",
            payload={
                "prompt": f"private prompt {secret}",
                "reasoning": f"hidden reasoning {secret}",
                "api_key": secret,
                "tool_output": f"private output {secret}",
                "safe_field": "visible",
            },
        ),
        TraceEvent(
            event_id="evt-2",
            sequence=2,
            occurred_at="2026-07-16T00:00:02+00:00",
            conversation_id="conv-export-server",
            run_id="run-export-server",
            event_type="run.completed",
            component="harness",
            status="completed",
            payload={"stop_reason": "done"},
        ),
    )


def _exporter(port: int, *, timeout: float = 1.0, token: str | None = None):
    return HttpTraceExporter(
        "https://collector.test/v1/traces",
        policy=ExternalExportPolicy(
            enabled=True,
            allowed_hosts=("collector.test",),
            timeout_seconds=timeout,
        ),
        bearer_token=token,
        urlopen=_route_to_localhost(port),
    )


def test_mock_collector_receives_redacted_envelope_and_out_of_band_auth() -> None:
    trace_secret = "trace-secret-value"
    bearer_token = "collector-bearer-secret"
    with _mock_collector() as (port, handler):
        summary = _exporter(port, token=bearer_token).export_run(
            _Reader(_events(trace_secret)),
            "run-export-server",
        )

    assert summary.status_code == 200
    assert summary.request_id == "mock-collector-request"
    assert summary.endpoint_host == "collector.test"
    assert len(handler.received) == 1
    received = handler.received[0]
    assert received["path"] == "/v1/traces"
    assert received["headers"]["authorization"] == f"Bearer {bearer_token}"

    encoded = received["body"].decode("utf-8")
    envelope = json.loads(encoded)
    assert envelope["event_count"] == 2
    assert envelope["events"][0]["payload"]["safe_field"] == "visible"
    assert envelope["events"][0]["payload"]["api_key"] == "<REDACTED>"
    assert envelope["events"][0]["payload"]["prompt"]["redacted"] is True
    assert trace_secret not in encoded
    assert bearer_token not in encoded


@pytest.mark.parametrize("status_code", [400, 401, 429, 500])
def test_mock_collector_http_failures_are_sanitized(status_code: int) -> None:
    response_secret = "collector-response-secret"
    with _mock_collector(
        status_code=status_code,
        response_body=f'{{"error":"{response_secret}"}}'.encode(),
    ) as (port, _handler):
        with pytest.raises(ExternalExportError) as caught:
            _exporter(port).export_run(
                _Reader(_events()),
                "run-export-server",
            )

    assert str(caught.value) == f"external export failed with HTTP {status_code}"
    assert response_secret not in str(caught.value)


def test_mock_collector_timeout_is_bounded_and_sanitized() -> None:
    with _mock_collector(delay_seconds=0.25) as (port, _handler):
        started = time.monotonic()
        with pytest.raises(ExternalExportError, match="timed out"):
            _exporter(port, timeout=0.05).export_run(
                _Reader(_events()),
                "run-export-server",
            )
        elapsed = time.monotonic() - started

    assert elapsed < 1.0


def test_mock_collector_connection_failure_is_sanitized() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    unused_port = int(probe.getsockname()[1])
    probe.close()

    with pytest.raises(ExternalExportError, match="failed to connect"):
        _exporter(unused_port, timeout=0.1).export_run(
            _Reader(_events()),
            "run-export-server",
        )
