"""Minimal synchronous Language Server Protocol client over stdio JSON-RPC."""

from __future__ import annotations

from collections import deque
from pathlib import Path
import json
import queue
import subprocess
from threading import Condition, Lock, Thread
import time
from typing import Any, Callable, Mapping, Sequence


class LSPError(RuntimeError):
    pass


class LSPTimeoutError(LSPError):
    pass


class LSPProtocolError(LSPError):
    pass


class LSPProcessError(LSPError):
    pass


class JsonRpcTransport:
    """Thread-safe request transport with framed stdout parsing."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        notification_handler: Callable[[str, Any], None] | None = None,
        stderr_tail_lines: int = 100,
    ) -> None:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("language server command must contain non-empty strings")
        self.command = tuple(command)
        self.cwd = cwd
        self._notification_handler = notification_handler
        try:
            self._process = subprocess.Popen(
                self.command,
                cwd=str(cwd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            raise LSPProcessError(
                f"language server could not start: {self.command[0]}"
            ) from exc
        if self._process.stdin is None or self._process.stdout is None:
            self._process.kill()
            raise LSPProcessError("language server stdio pipes are unavailable")
        self._write_lock = Lock()
        self._pending_lock = Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._next_id = 1
        self._closed = False
        self.stderr_tail: deque[str] = deque(maxlen=stderr_tail_lines)
        self._reader = Thread(
            target=self._read_loop,
            name="paperclaw-lsp-stdout",
            daemon=True,
        )
        self._stderr_reader = Thread(
            target=self._stderr_loop,
            name="paperclaw-lsp-stderr",
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    def request(self, method: str, params: Any, *, timeout: float) -> Any:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        try:
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise LSPTimeoutError(f"LSP request timed out: {method}") from exc
        if "error" in response:
            error = response.get("error") or {}
            raise LSPProtocolError(
                f"LSP error for {method}: {error.get('code')} {error.get('message')}"
            )
        return response.get("result")

    def notify(self, method: str, params: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self, *, timeout: float = 2.0) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=timeout)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    pass
        self._fail_pending("language server transport closed")

    def _send(self, payload: Mapping[str, Any]) -> None:
        if self._closed:
            raise LSPProcessError("language server transport is closed")
        if self._process.poll() is not None:
            raise LSPProcessError(
                f"language server exited with code {self._process.returncode}"
            )
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        frame = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        stdin = self._process.stdin
        if stdin is None:
            raise LSPProcessError("language server stdin is unavailable")
        try:
            with self._write_lock:
                stdin.write(frame)
                stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise LSPProcessError("language server stdin failed") from exc

    def _read_loop(self) -> None:
        stdout = self._process.stdout
        assert stdout is not None
        try:
            while not self._closed:
                headers: dict[str, str] = {}
                while True:
                    line = stdout.readline()
                    if not line:
                        raise EOFError
                    if line in {b"\r\n", b"\n"}:
                        break
                    decoded = line.decode("ascii", errors="replace").strip()
                    if ":" not in decoded:
                        raise LSPProtocolError("invalid LSP header")
                    key, value = decoded.split(":", 1)
                    headers[key.lower().strip()] = value.strip()
                try:
                    length = int(headers["content-length"])
                except (KeyError, ValueError) as exc:
                    raise LSPProtocolError("missing or invalid Content-Length") from exc
                if length < 0 or length > 20_000_000:
                    raise LSPProtocolError("LSP frame exceeds safety limit")
                body = stdout.read(length)
                if len(body) != length:
                    raise EOFError
                message = json.loads(body.decode("utf-8"))
                if not isinstance(message, dict):
                    raise LSPProtocolError("JSON-RPC message must be an object")
                self._dispatch(message)
        except Exception as exc:
            if not self._closed:
                self._fail_pending(f"LSP reader stopped: {type(exc).__name__}: {exc}")

    def _dispatch(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if isinstance(request_id, int):
            with self._pending_lock:
                response_queue = self._pending.pop(request_id, None)
            if response_queue is not None:
                response_queue.put_nowait(message)
            return
        method = message.get("method")
        if isinstance(method, str) and self._notification_handler is not None:
            try:
                self._notification_handler(method, message.get("params"))
            except Exception:
                pass

    def _stderr_loop(self) -> None:
        stderr = self._process.stderr
        if stderr is None:
            return
        try:
            for raw in iter(stderr.readline, b""):
                self.stderr_tail.append(raw.decode("utf-8", errors="replace").rstrip())
        except OSError:
            return

    def _fail_pending(self, message: str) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        response = {
            "jsonrpc": "2.0",
            "error": {"code": -32099, "message": message},
        }
        for response_queue in pending:
            try:
                response_queue.put_nowait(response)
            except queue.Full:
                pass


class LSPClient:
    """Lifecycle and read-only semantic operations for one language server."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        workspace: Path,
        language_id: str,
        request_timeout: float = 10.0,
        initialize_timeout: float = 20.0,
    ) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.language_id = language_id
        self.request_timeout = request_timeout
        self._diagnostics: dict[str, list[dict[str, Any]]] = {}
        self._diagnostic_condition = Condition()
        self._opened_versions: dict[str, int] = {}
        self._transport = JsonRpcTransport(
            command,
            cwd=self.workspace,
            notification_handler=self._notification,
        )
        root_uri = self.workspace.as_uri()
        self.capabilities = self._transport.request(
            "initialize",
            {
                "processId": None,
                "clientInfo": {"name": "PaperClaw", "version": "0.21"},
                "rootUri": root_uri,
                "workspaceFolders": [{"uri": root_uri, "name": self.workspace.name}],
                "capabilities": {
                    "textDocument": {
                        "publishDiagnostics": {"relatedInformation": True},
                        "definition": {"linkSupport": True},
                        "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                    },
                    "workspace": {"symbol": {"dynamicRegistration": False}},
                },
            },
            timeout=initialize_timeout,
        ) or {}
        self._transport.notify("initialized", {})

    def diagnostics(self, path: Path, *, wait_seconds: float = 1.0) -> list[dict[str, Any]]:
        uri = self.open_document(path)
        deadline = time.monotonic() + max(0.0, wait_seconds)
        with self._diagnostic_condition:
            while uri not in self._diagnostics and time.monotonic() < deadline:
                self._diagnostic_condition.wait(timeout=deadline - time.monotonic())
            return list(self._diagnostics.get(uri, []))

    def definition(self, path: Path, line: int, character: int) -> Any:
        return self._position_request("textDocument/definition", path, line, character)

    def references(
        self,
        path: Path,
        line: int,
        character: int,
        *,
        include_declaration: bool = False,
    ) -> Any:
        return self._position_request(
            "textDocument/references",
            path,
            line,
            character,
            extra={"context": {"includeDeclaration": include_declaration}},
        )

    def hover(self, path: Path, line: int, character: int) -> Any:
        return self._position_request("textDocument/hover", path, line, character)

    def document_symbols(self, path: Path) -> Any:
        uri = self.open_document(path)
        return self._transport.request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
            timeout=self.request_timeout,
        )

    def workspace_symbols(self, query: str) -> Any:
        return self._transport.request(
            "workspace/symbol",
            {"query": query},
            timeout=self.request_timeout,
        )

    def open_document(self, path: Path) -> str:
        resolved = path.resolve(strict=True)
        uri = resolved.as_uri()
        text = resolved.read_text(encoding="utf-8")
        version = self._opened_versions.get(uri, 0) + 1
        self._opened_versions[uri] = version
        method = "textDocument/didOpen" if version == 1 else "textDocument/didChange"
        if version == 1:
            params = {
                "textDocument": {
                    "uri": uri,
                    "languageId": self.language_id,
                    "version": version,
                    "text": text,
                }
            }
        else:
            params = {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}],
            }
        self._transport.notify(method, params)
        return uri

    def close(self) -> None:
        try:
            self._transport.request("shutdown", None, timeout=2.0)
            self._transport.notify("exit", None)
        except LSPError:
            pass
        finally:
            self._transport.close()

    def _position_request(
        self,
        method: str,
        path: Path,
        line: int,
        character: int,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> Any:
        if isinstance(line, bool) or not isinstance(line, int) or line < 0:
            raise ValueError("line must be a non-negative integer")
        if isinstance(character, bool) or not isinstance(character, int) or character < 0:
            raise ValueError("character must be a non-negative integer")
        uri = self.open_document(path)
        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        }
        if extra:
            params.update(extra)
        return self._transport.request(method, params, timeout=self.request_timeout)

    def _notification(self, method: str, params: Any) -> None:
        if method != "textDocument/publishDiagnostics" or not isinstance(params, Mapping):
            return
        uri = params.get("uri")
        diagnostics = params.get("diagnostics")
        if not isinstance(uri, str) or not isinstance(diagnostics, list):
            return
        safe = [item for item in diagnostics if isinstance(item, dict)]
        with self._diagnostic_condition:
            self._diagnostics[uri] = safe
            self._diagnostic_condition.notify_all()


__all__ = [
    "JsonRpcTransport",
    "LSPClient",
    "LSPError",
    "LSPProcessError",
    "LSPProtocolError",
    "LSPTimeoutError",
]
