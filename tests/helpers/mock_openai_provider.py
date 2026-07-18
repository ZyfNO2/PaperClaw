from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any


_DONE_CONTENT = json.dumps(
    {
        "action": "done",
        "arguments": {
            "result": "process-acceptance-complete",
            "verification": "",
            "remaining_issues": [],
        },
    },
    separators=(",", ":"),
)


class ProviderState:
    def __init__(self, path: Path, mode: str) -> None:
        self.path = path
        self.mode = mode
        self.blocked_path = path.with_suffix(".blocked")
        self._lock = Lock()
        self.requests = 0
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.requests = int(payload.get("requests", 0))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                self.requests = 0

    def next_request(self, payload: dict[str, Any]) -> tuple[int, bool]:
        with self._lock:
            self.requests += 1
            request_number = self.requests
            self._write(
                {
                    "requests": request_number,
                    "last_model": payload.get("model"),
                }
            )
            should_block = self.mode == "block-once" and request_number == 1
            if should_block:
                self.blocked_path.write_text("blocked\n", encoding="utf-8")
            return request_number, should_block

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def build_handler(state: ProviderState, api_key: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "PaperClawMockProvider/0.16"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if self.path == "/v1/models":
                if not self._authorized():
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {"object": "list", "data": [{"id": "mock-model"}]},
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/chat/completions":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            if not self._authorized():
                return
            payload = self._read_json()
            if payload is None:
                return
            request_number, should_block = state.next_request(payload)
            if should_block:
                time.sleep(60)
            response = {
                "id": f"chatcmpl-mock-{request_number}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": _DONE_CONTENT,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
            try:
                self._send_json(
                    HTTPStatus.OK,
                    response,
                    extra_headers={"X-Request-ID": f"mock-{request_number}"},
                )
            except (BrokenPipeError, ConnectionResetError):
                return

        def _authorized(self) -> bool:
            if self.headers.get("Authorization") == f"Bearer {api_key}":
                return True
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": {"message": "invalid API key"}},
            )
            return False

        def _read_json(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": {"message": "invalid JSON"}},
                )
                return None
            if not isinstance(payload, dict):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": {"message": "request must be an object"}},
                )
                return None
            return payload

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict[str, Any],
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--mode", choices=("success", "block-once"), default="success")
    parser.add_argument("--api-key", default="acceptance-key")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    state = ProviderState(args.state_file, args.mode)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        build_handler(state, args.api_key),
    )
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
