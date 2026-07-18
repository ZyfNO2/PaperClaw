from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROVIDER_SCRIPT = _REPO_ROOT / "tests" / "helpers" / "mock_openai_provider.py"
_TERMINAL = {"completed", "failed", "stopped", "blocked", "budget_exhausted", "recovery_required"}


@dataclass
class ManagedProcess:
    process: subprocess.Popen[bytes]
    log_path: Path
    log_handle: Any

    def stop(self, *, force: bool = False) -> None:
        if self.process.poll() is None:
            if force:
                self.process.kill()
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log_handle.close()

    def diagnostics(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")[-8_000:]
        except OSError:
            return "<log unavailable>"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_process(command: list[str], *, env: dict[str, str], log_path: Path) -> ManagedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        command,
        cwd=_REPO_ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return ManagedProcess(process, log_path, log_handle)


def _provider_env(provider_port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PAPERCLAW_API_KEY": "acceptance-key",
            "PAPERCLAW_BASE_URL": f"http://127.0.0.1:{provider_port}/v1",
            "PAPERCLAW_MODEL": "mock-model",
            "PAPERCLAW_PROVIDER": "acceptance-mock",
            "PAPERCLAW_PROVIDER_MAX_ATTEMPTS": "1",
            "PAPERCLAW_TIMEOUT_SECONDS": "15",
        }
    )
    return env


@contextmanager
def _provider_process(
    tmp_path: Path,
    *,
    mode: str,
) -> Iterator[tuple[ManagedProcess, int, Path]]:
    port = _free_port()
    state_file = tmp_path / f"provider-{mode}.json"
    managed = _start_process(
        [
            sys.executable,
            str(_PROVIDER_SCRIPT),
            "--port",
            str(port),
            "--state-file",
            str(state_file),
            "--mode",
            mode,
        ],
        env=os.environ.copy(),
        log_path=tmp_path / f"provider-{mode}.log",
    )
    try:
        _wait_health(f"http://127.0.0.1:{port}/health", managed)
        yield managed, port, state_file
    finally:
        managed.stop()


def _start_service(
    tmp_path: Path,
    *,
    provider_port: int,
    database: Path,
    label: str,
) -> tuple[ManagedProcess, str]:
    port = _free_port()
    managed = _start_process(
        [
            sys.executable,
            "-m",
            "paperclaw.service.entrypoint",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--database",
            str(database),
            "--max-active-runs",
            "1",
            "--lease-seconds",
            "0.8",
            "--heartbeat-seconds",
            "0.2",
            "--queue-timeout-seconds",
            "10",
            "--run-timeout-seconds",
            "20",
        ],
        env=_provider_env(provider_port),
        log_path=tmp_path / f"service-{label}.log",
    )
    origin = f"http://127.0.0.1:{port}"
    _wait_health(f"{origin}/health", managed)
    return managed, origin


def _wait_health(url: str, process: ManagedProcess, *, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise AssertionError(
                f"process exited with {process.process.returncode}\n{process.diagnostics()}"
            )
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, HTTPError, URLError) as exc:
            last_error = exc
        time.sleep(0.05)
    raise AssertionError(
        f"health endpoint did not become ready: {last_error}\n{process.diagnostics()}"
    )


def _json_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    data = None
    request_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    assert isinstance(value, dict)
    return value


def _run_payload(workspace: Path) -> dict[str, Any]:
    return {
        "task": "Return the deterministic process acceptance result.",
        "workspace": str(workspace),
        "conversation_id": "process-acceptance",
        "client_id": "pytest",
        "enable_verification_gate": False,
        "disconnect_policy": "detach_on_disconnect",
        "limits": {
            "max_steps": 3,
            "max_model_calls": 2,
            "max_tool_calls": 1,
        },
    }


def _wait_terminal(origin: str, run_id: str, process: ManagedProcess, *, timeout: float = 25) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_view: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise AssertionError(
                f"service exited with {process.process.returncode}\n{process.diagnostics()}"
            )
        last_view = _json_request("GET", f"{origin}/v1/runs/{run_id}")
        if last_view.get("status") in _TERMINAL:
            return last_view
        time.sleep(0.05)
    raise AssertionError(
        f"run did not become terminal; last={last_view}\n{process.diagnostics()}"
    )


def _wait_for_path(path: Path, process: ManagedProcess, *, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.process.poll() is not None:
            raise AssertionError(
                f"process exited with {process.process.returncode}\n{process.diagnostics()}"
            )
        time.sleep(0.05)
    raise AssertionError(f"marker was not created: {path}\n{process.diagnostics()}")


def _read_sse(origin: str, run_id: str, *, after: int = 0) -> list[dict[str, Any]]:
    request = Request(
        f"{origin}/v1/runs/{run_id}/events",
        headers={"Last-Event-ID": str(after)},
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8").replace("\r\n", "\n")
    events: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        if not block.strip() or block.lstrip().startswith(":"):
            continue
        item: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                item["id"] = int(line[4:])
            elif line.startswith("event: "):
                item["event"] = line[7:]
            elif line.startswith("data: "):
                item["data"] = json.loads(line[6:])
        if item:
            events.append(item)
    return events


def test_real_uvicorn_provider_sse_and_idempotency_round_trip(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = tmp_path / "service.sqlite3"

    with _provider_process(tmp_path, mode="success") as (_, provider_port, _):
        service, origin = _start_service(
            tmp_path,
            provider_port=provider_port,
            database=database,
            label="round-trip",
        )
        try:
            payload = _run_payload(workspace)
            submitted = _json_request(
                "POST",
                f"{origin}/v1/runs",
                payload,
                headers={"Idempotency-Key": "process-round-trip"},
            )
            assert submitted["created"] is True
            run_id = submitted["run"]["service_run_id"]

            terminal = _wait_terminal(origin, run_id, service)
            assert terminal["status"] == "completed"
            assert terminal["output"] == "process-acceptance-complete"
            assert terminal["model_calls"] == 1

            replayed_submission = _json_request(
                "POST",
                f"{origin}/v1/runs",
                payload,
                headers={"Idempotency-Key": "process-round-trip"},
            )
            assert replayed_submission["created"] is False
            assert replayed_submission["run"]["service_run_id"] == run_id

            events = _read_sse(origin, run_id)
            event_names = [item["event"] for item in events]
            event_ids = [item["id"] for item in events]
            assert event_ids == sorted(set(event_ids))
            assert "service.run.accepted" in event_names
            assert "run.started" in event_names
            assert "model.completed" in event_names
            assert "service.run.finalized" in event_names

            cursor = event_ids[0]
            resumed = _read_sse(origin, run_id, after=cursor)
            assert resumed
            assert all(item["id"] > cursor for item in resumed)
        finally:
            service.stop()


def test_kill_restart_reconciles_inflight_provider_request(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = tmp_path / "service.sqlite3"

    with _provider_process(tmp_path, mode="block-once") as (_, provider_port, state_file):
        first_service, first_origin = _start_service(
            tmp_path,
            provider_port=provider_port,
            database=database,
            label="before-kill",
        )
        payload = _run_payload(workspace)
        submitted = _json_request(
            "POST",
            f"{first_origin}/v1/runs",
            payload,
            headers={"Idempotency-Key": "process-restart"},
        )
        run_id = submitted["run"]["service_run_id"]
        _wait_for_path(state_file.with_suffix(".blocked"), first_service)

        first_service.stop(force=True)
        time.sleep(1.2)

        second_service, second_origin = _start_service(
            tmp_path,
            provider_port=provider_port,
            database=database,
            label="after-restart",
        )
        try:
            terminal = _wait_terminal(second_origin, run_id, second_service)
            assert terminal["status"] == "completed"
            assert terminal["output"] == "process-acceptance-complete"

            events = _read_sse(second_origin, run_id)
            event_names = [item["event"] for item in events]
            assert "service.run.reconciled" in event_names
            assert event_names.count("service.run.finalized") == 1

            provider_state = json.loads(state_file.read_text(encoding="utf-8"))
            assert provider_state["requests"] == 2
        finally:
            second_service.stop()
