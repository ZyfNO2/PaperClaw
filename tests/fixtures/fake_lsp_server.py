from __future__ import annotations

import json
import sys
import time


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower().strip()] = value.strip()
    length = int(headers["content-length"])
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send(payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def response(request_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    send(payload)


def main():
    while True:
        message = read_message()
        if message is None:
            return 0
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            response(
                request_id,
                {
                    "capabilities": {
                        "definitionProvider": True,
                        "referencesProvider": True,
                        "hoverProvider": True,
                        "documentSymbolProvider": True,
                        "workspaceSymbolProvider": True,
                        "textDocumentSync": 1,
                    }
                },
            )
        elif method in {"initialized", "textDocument/didChange"}:
            continue
        elif method == "textDocument/didOpen":
            document = params["textDocument"]
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {
                        "uri": document["uri"],
                        "version": document.get("version"),
                        "diagnostics": [
                            {
                                "range": {
                                    "start": {"line": 0, "character": 0},
                                    "end": {"line": 0, "character": 3},
                                },
                                "severity": 2,
                                "code": "FAKE001",
                                "source": "fake-lsp",
                                "message": "deterministic diagnostic",
                            }
                        ],
                    },
                }
            )
        elif method == "textDocument/definition":
            uri = params["textDocument"]["uri"]
            response(
                request_id,
                {
                    "uri": uri,
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 3},
                    },
                },
            )
        elif method == "textDocument/references":
            uri = params["textDocument"]["uri"]
            response(
                request_id,
                [
                    {
                        "uri": uri,
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 3},
                        },
                    },
                    {
                        "uri": uri,
                        "range": {
                            "start": {"line": 1, "character": 0},
                            "end": {"line": 1, "character": 3},
                        },
                    },
                ],
            )
        elif method == "textDocument/hover":
            response(
                request_id,
                {
                    "contents": {
                        "kind": "markdown",
                        "value": "```python\ndef demo() -> int\n```",
                    }
                },
            )
        elif method == "textDocument/documentSymbol":
            response(
                request_id,
                [
                    {
                        "name": "demo",
                        "kind": 12,
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 1, "character": 8},
                        },
                        "selectionRange": {
                            "start": {"line": 0, "character": 4},
                            "end": {"line": 0, "character": 8},
                        },
                    }
                ],
            )
        elif method == "workspace/symbol":
            response(
                request_id,
                [
                    {
                        "name": params.get("query") or "demo",
                        "kind": 12,
                        "location": {
                            "uri": "file:///workspace/demo.py",
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 4},
                            },
                        },
                    }
                ],
            )
        elif method == "paperclaw/sleep":
            time.sleep(float(params.get("seconds", 0.2)))
            response(request_id, {"slept": True})
        elif method == "paperclaw/error":
            response(
                request_id,
                error={"code": -32001, "message": "deterministic failure"},
            )
        elif method == "shutdown":
            response(request_id, None)
        elif method == "exit":
            return 0
        elif request_id is not None:
            response(
                request_id,
                error={"code": -32601, "message": f"unknown method: {method}"},
            )


if __name__ == "__main__":
    raise SystemExit(main())
