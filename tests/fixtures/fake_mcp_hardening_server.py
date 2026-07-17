"""Failure-injection stdio MCP server for transport hardening tests."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

PROTOCOL_VERSION = "2025-11-25"


def _write(message: Any) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _result(request_id: Any, result: Any) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "result": result})


def _tool() -> dict[str, Any]:
    return {
        "name": "echo",
        "description": "Echo one text value",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    }


def _initialize(request_id: Any) -> None:
    _result(
        request_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "hardening-server", "version": "1"},
        },
    )


def serve(mode: str) -> int:
    if mode == "stderr_flood":
        sys.stderr.buffer.write(b"e" * 2_000_000)
        sys.stderr.flush()

    initialized = False
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")

        if request_id is None:
            if method == "notifications/initialized":
                initialized = True
            continue

        if method == "initialize":
            if mode == "block_initialize":
                time.sleep(60)
                continue
            _initialize(request_id)
            continue

        if not initialized:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32002, "message": "not initialized"},
                }
            )
            continue

        if method == "tools/list":
            if mode == "oversized_no_newline":
                sys.stdout.buffer.write(b"{" + b"x" * 4096)
                sys.stdout.buffer.flush()
                time.sleep(60)
                continue
            if mode == "pagination_loop":
                _result(request_id, {"tools": [], "nextCursor": "loop"})
                continue
            if mode == "duplicate_tool":
                cursor = message.get("params", {}).get("cursor")
                if cursor is None:
                    _result(request_id, {"tools": [_tool()], "nextCursor": "page-2"})
                else:
                    _result(request_id, {"tools": [_tool()]})
                continue
            if mode == "deep_json":
                nested: Any = "leaf"
                for _ in range(200):
                    nested = {"value": nested}
                _result(request_id, {"tools": [], "padding": nested})
                continue
            _result(request_id, {"tools": [_tool()]})
            continue

        if method == "tools/call":
            if mode == "late_call":
                time.sleep(0.30)
            params = message.get("params", {})
            text = params.get("arguments", {}).get("text", "")
            _result(
                request_id,
                {
                    "content": [{"type": "text", "text": text}],
                    "structuredContent": {"echoed": text},
                    "isError": False,
                },
            )
            continue

        _write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "method not found"},
            }
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    args = parser.parse_args()
    return serve(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
