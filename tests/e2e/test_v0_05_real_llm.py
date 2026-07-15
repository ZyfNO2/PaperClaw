"""Real-provider end-to-end acceptance tests for the v0.05 QueryEngine MVP.

These tests are NOT run in ordinary CI because they call a live LLM API, require
secrets, incur cost, and are inherently non-deterministic. Run them manually or
via the dedicated ``real-llm-e2e`` GitHub Actions workflow:

    python -m pytest tests/e2e/test_v0_05_real_llm.py -v -m real_llm

The tests expect the same environment variables used by ``OpenAICompatibleModel.from_env``:

* ``PAPERCLAW_API_KEY``
* ``PAPERCLAW_BASE_URL``
* ``PAPERCLAW_MODEL``

Each test uses its own temporary workspace so they can be executed in parallel
without filesystem collisions.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.models.adapters import OpenAICompatibleModel


pytestmark = pytest.mark.real_llm


def _load_dotenv() -> None:
    """Mirror the CLI dotenv loading so tests can discover secrets locally."""
    dotenv = Path.cwd() / ".env"
    if not dotenv.exists():
        return
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip())


def _require_env() -> dict[str, str]:
    """Return the provider configuration or skip the test if secrets are missing."""
    _load_dotenv()
    required = {
        "PAPERCLAW_API_KEY": os.getenv("PAPERCLAW_API_KEY"),
        "PAPERCLAW_BASE_URL": os.getenv("PAPERCLAW_BASE_URL"),
        "PAPERCLAW_MODEL": os.getenv("PAPERCLAW_MODEL"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        pytest.skip(f"missing real-LLM environment variables: {', '.join(missing)}")
    return required  # type: ignore[return-value]


def _make_engine(tmp_path: Path, limits: RunLimits) -> tuple[QueryEngine, list[tuple[str, dict[str, Any]]]]:
    """Build a QueryEngine wired to a real provider for one isolated run."""
    env = _require_env()
    model = OpenAICompatibleModel(
        api_key=env["PAPERCLAW_API_KEY"],
        base_url=env["PAPERCLAW_BASE_URL"],
        model=env["PAPERCLAW_MODEL"],
        timeout=120,
    )
    events: list[tuple[str, dict[str, Any]]] = []
    executor = AgentRuntimeExecutor(model, tmp_path)
    engine = QueryEngine(
        executor,
        conversation_id=f"real-llm-{tmp_path.name}",
        event_handler=lambda event_type, payload: events.append((event_type, dict(payload))),
    )
    return engine, events


def _terminal_events(events: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (event_type, payload)
        for event_type, payload in events
        if event_type in {"run.completed", "run.failed", "run.stopped"}
    ]


def test_real_llm_create_run_verify(tmp_path: Path) -> None:
    """E2E-01: real LLM creates hello.py, runs it, and verifies the output."""
    engine, events = _make_engine(
        tmp_path,
        RunLimits(max_steps=8, max_model_calls=8, max_tool_calls=8),
    )

    result = engine.submit(
        "Create a file named hello.py in the workspace that prints exactly "
        "'PaperClaw v0.05 REAL LLM OK.' when run with python. "
        "Run the file with python, confirm the output, then finish with done.",
    )

    written = tmp_path / "hello.py"
    assert written.exists(), f"hello.py was not created; terminal output: {result.output!r}"
    content = written.read_text(encoding="utf-8")
    assert "PaperClaw v0.05 REAL LLM OK." in content, f"unexpected file content: {content!r}"

    assert result.status == "completed", f"expected completed, got {result.status} ({result.stop_reason})"
    assert result.model_calls > 0, "expected at least one real model call"
    assert result.tool_calls > 0, "expected at least one real tool call"
    terminal = _terminal_events(events)
    assert len(terminal) == 1, f"expected exactly one terminal event, got {len(terminal)}"
    assert terminal[0][0] == "run.completed"


def test_real_llm_cancel_at_safe_boundary(tmp_path: Path) -> None:
    """E2E-04: an accepted stop during a real tool run ends as stopped."""

    engine, events = _make_engine(
        tmp_path,
        RunLimits(max_steps=8, max_model_calls=8, max_tool_calls=8),
    )
    results = []
    errors = []

    def submit() -> None:
        try:
            results.append(
                engine.submit(
                    "Use the bash tool to run exactly: "
                    'python -c "import time; time.sleep(5); print(\'done\')". '
                    "After that command, continue working until told to stop.",
                )
            )
        except Exception as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    thread = threading.Thread(target=submit, daemon=True)
    thread.start()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if any(event == "tool.started" for event, _ in events):
            break
        time.sleep(0.05)
    else:
        pytest.fail("real model did not start a tool call")
    run_id = next(payload["run_id"] for event, payload in events if event == "run.started")

    assert engine.request_stop(run_id, "user_requested") is True
    thread.join(timeout=90)

    assert not thread.is_alive(), "cancelled real-provider run did not reach a safe boundary"
    assert not errors, f"real-provider run raised unexpectedly: {errors!r}"
    assert results[0].status == "stopped"
    assert results[0].stop_reason == "user_requested"
    terminal = _terminal_events(events)
    assert len(terminal) == 1, f"expected exactly one terminal event, got {len(terminal)}"
    assert terminal[0][0] == "run.stopped"


def test_real_llm_repair_after_error(tmp_path: Path) -> None:
    """E2E-02: real LLM creates a broken file, observes failure, repairs it, and re-verifies."""
    engine, events = _make_engine(
        tmp_path,
        RunLimits(max_steps=12, max_model_calls=12, max_tool_calls=12),
    )

    result = engine.submit(
        "Create a file named hello.py in the workspace that intentionally contains "
        "a Python syntax error or runtime error. Run it with python, observe the error, "
        "then fix the file so it prints exactly 'PaperClaw v0.05 REPAIR OK.' and run it again. "
        "Finish with done only after the second run succeeds.",
    )

    written = tmp_path / "hello.py"
    assert written.exists(), f"hello.py was not created; terminal output: {result.output!r}"
    content = written.read_text(encoding="utf-8")
    assert "PaperClaw v0.05 REPAIR OK." in content, f"final file content did not match: {content!r}"

    # The run must have observed at least one failing tool result and still recovered.
    tool_results = [
        payload
        for event_type, payload in events
        if event_type == "tool.completed" or event_type == "tool.failed"
    ]
    assert any(not payload.get("ok", True) for payload in tool_results), "expected at least one failing tool result"
    assert any(payload.get("ok", False) for payload in tool_results), "expected at least one succeeding tool result"

    assert result.status == "completed", f"expected completed, got {result.status} ({result.stop_reason})"
    assert result.model_calls > 1, "repair loop should require more than one model call"
    assert result.tool_calls > 1, "repair loop should require more than one tool call"
    terminal = _terminal_events(events)
    assert len(terminal) == 1, f"expected exactly one terminal event, got {len(terminal)}"
    assert terminal[0][0] == "run.completed"


def test_real_llm_model_budget_boundary(tmp_path: Path) -> None:
    """E2E-03: with max_model_calls=1, the provider is called exactly once and the run stops."""
    env = _require_env()
    call_log: list[int] = []

    class _CountingModel:
        """Thin wrapper that records every real provider invocation."""

        def __init__(self, inner: OpenAICompatibleModel) -> None:
            self._inner = inner

        def complete(self, prompt: str):
            call_log.append(1)
            return self._inner.complete(prompt)

    model = _CountingModel(
        OpenAICompatibleModel(
            api_key=env["PAPERCLAW_API_KEY"],
            base_url=env["PAPERCLAW_BASE_URL"],
            model=env["PAPERCLAW_MODEL"],
            timeout=120,
        )
    )

    events: list[tuple[str, dict[str, Any]]] = []
    executor = AgentRuntimeExecutor(model, tmp_path)
    engine = QueryEngine(
        executor,
        conversation_id=f"real-llm-budget-{tmp_path.name}",
        event_handler=lambda event_type, payload: events.append((event_type, dict(payload))),
    )

    result = engine.submit(
        "Create a file named hello.py that prints 'hello' and run it with python.",
        limits=RunLimits(max_steps=8, max_model_calls=1, max_tool_calls=8),
    )

    assert len(call_log) == 1, f"provider must be called exactly once, was called {len(call_log)} times"
    assert result.status == "budget_exhausted", f"expected budget_exhausted, got {result.status}"
    assert result.stop_reason == "max_model_calls"
    assert result.model_calls == 1
