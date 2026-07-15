#!/usr/bin/env python3
"""Repeatable live Mistral acceptance for PaperClaw v0.07 traces.

Required environment variables:
    PAPERCLAW_API_KEY
    PAPERCLAW_BASE_URL
    PAPERCLAW_MODEL

Optional environment variables:
    PAPERCLAW_PROVIDER (default: mistral)
    PAPERCLAW_TIMEOUT_SECONDS (default: 120)

The script performs one real provider call through the production
OpenAI-compatible adapter, persists the Run in SQLite, exports TraceEvent v1
JSONL, validates ordering/terminal/provider metadata, and verifies that the API
key does not occur in SQLite, JSONL, or the sanitized summary.

Exit codes:
    0: live acceptance passed
    1: provider/runtime/trace acceptance failed
    2: required configuration is missing or malformed
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperclaw.context.repository import SQLiteRepository
from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.models.adapters import OpenAICompatibleModel
from paperclaw.tools.registry import ToolRegistry
from paperclaw.trace import (
    RepositoryTraceReader,
    TraceRedactor,
    export_trace_jsonl,
    load_trace_jsonl,
)

TASK = (
    "Do not call any tool. Finish directly with a done response whose result "
    "contains exactly: PaperClaw v0.07 Mistral trace smoke OK."
)
EXPECTED_TEXT = "PaperClaw v0.07 Mistral trace smoke OK."
WORK_DIR = REPO_ROOT / "tmp" / "v0_07_mistral_trace_smoke"
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "v0_07" / "live_smoke"
DATABASE = WORK_DIR / "paperclaw.db"
TRACE_JSONL = ARTIFACT_DIR / "trace.jsonl"
SUMMARY_JSON = ARTIFACT_DIR / "summary.json"


def _load_dotenv() -> None:
    dotenv = REPO_ROOT / ".env"
    if not dotenv.is_file():
        return
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip())


def _require_environment() -> dict[str, str]:
    _load_dotenv()
    values = {
        "PAPERCLAW_API_KEY": os.getenv("PAPERCLAW_API_KEY", "").strip(),
        "PAPERCLAW_BASE_URL": os.getenv("PAPERCLAW_BASE_URL", "").strip(),
        "PAPERCLAW_MODEL": os.getenv("PAPERCLAW_MODEL", "").strip(),
        "PAPERCLAW_PROVIDER": os.getenv("PAPERCLAW_PROVIDER", "mistral").strip(),
        "PAPERCLAW_TIMEOUT_SECONDS": os.getenv(
            "PAPERCLAW_TIMEOUT_SECONDS",
            "120",
        ).strip(),
    }
    missing = [
        name
        for name in (
            "PAPERCLAW_API_KEY",
            "PAPERCLAW_BASE_URL",
            "PAPERCLAW_MODEL",
        )
        if not values[name]
    ]
    if missing:
        raise ValueError(
            "missing environment variables: " + ", ".join(missing)
        )
    if len(values["PAPERCLAW_API_KEY"]) < 8:
        raise ValueError("PAPERCLAW_API_KEY looks too short")
    parsed = urlparse(values["PAPERCLAW_BASE_URL"])
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("PAPERCLAW_BASE_URL must be an absolute HTTPS URL")
    timeout = float(values["PAPERCLAW_TIMEOUT_SECONDS"])
    if timeout <= 0 or timeout > 600:
        raise ValueError("PAPERCLAW_TIMEOUT_SECONDS must be in (0, 600]")
    return values


def _prepare_directories() -> None:
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if TRACE_JSONL.exists():
        TRACE_JSONL.unlink()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _secret_absent(path: Path, secret: str) -> bool:
    return secret.encode("utf-8") not in path.read_bytes()


def _write_summary(summary: dict[str, Any], secret: str) -> None:
    encoded = json.dumps(
        summary,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if secret in encoded:
        raise RuntimeError("refusing to write a summary containing the API key")
    SUMMARY_JSON.write_text(encoded, encoding="utf-8")


def main() -> int:
    try:
        env = _require_environment()
    except (TypeError, ValueError) as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return 2

    _prepare_directories()
    secret = env["PAPERCLAW_API_KEY"]
    timeout = float(env["PAPERCLAW_TIMEOUT_SECONDS"])
    host = urlparse(env["PAPERCLAW_BASE_URL"]).hostname or "unknown"
    repository = SQLiteRepository(DATABASE, migrate=True)

    try:
        model = OpenAICompatibleModel(
            api_key=secret,
            base_url=env["PAPERCLAW_BASE_URL"],
            model=env["PAPERCLAW_MODEL"],
            timeout=timeout,
            provider=env["PAPERCLAW_PROVIDER"],
        )
        result = QueryEngine(
            AgentRuntimeExecutor(
                model,
                WORK_DIR,
                registry=ToolRegistry([]),
                repository=repository,
                enable_verification_gate=False,
            ),
            conversation_id="v0-07-mistral-trace-smoke",
        ).submit(
            TASK,
            limits=RunLimits(
                max_steps=3,
                max_model_calls=2,
                max_tool_calls=1,
            ),
        )

        reader = RepositoryTraceReader(
            repository,
            redactor=TraceRedactor(secret_values=[secret]),
        )
        export = export_trace_jsonl(
            reader,
            result.run_id,
            TRACE_JSONL,
            require_terminal=True,
        )
        trace = load_trace_jsonl(TRACE_JSONL, require_terminal=True)
    finally:
        repository.close()

    event_types = [event.event_type for event in trace]
    model_events = [
        event
        for event in trace
        if event.event_type
        in {"model.started", "model.completed", "model.failed"}
    ]
    terminal_events = [
        event
        for event in trace
        if event.event_type
        in {"run.completed", "run.failed", "run.stopped", "run.cancelled"}
    ]
    provider_metadata_ok = bool(model_events) and all(
        event.provider == env["PAPERCLAW_PROVIDER"]
        and event.model == env["PAPERCLAW_MODEL"]
        for event in model_events
    )
    durations_ok = all(
        event.duration_ms is not None and event.duration_ms >= 0
        for event in model_events
        if event.event_type in {"model.completed", "model.failed"}
    )
    output_ok = bool(
        result.output
        and EXPECTED_TEXT.rstrip(" .") in result.output.rstrip(" .")
    )

    checks = {
        "run_completed": result.status == "completed",
        "expected_output": output_ok,
        "trace_starts_with_run_started": bool(trace)
        and trace[0].event_type == "run.started",
        "single_terminal": len(terminal_events) == 1,
        "terminal_is_completed": bool(terminal_events)
        and terminal_events[0].event_type == "run.completed",
        "provider_metadata": provider_metadata_ok,
        "duration_metadata": durations_ok,
        "sqlite_secret_absent": _secret_absent(DATABASE, secret),
        "jsonl_secret_absent": _secret_absent(TRACE_JSONL, secret),
        "round_trip_event_count": len(trace) == export.event_count,
    }
    passed = all(checks.values())

    summary = {
        "schema_version": 1,
        "scenario": "v0.07-mistral-durable-trace-smoke",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "provider": env["PAPERCLAW_PROVIDER"],
        "provider_host": host,
        "model": env["PAPERCLAW_MODEL"],
        "timeout_seconds": timeout,
        "result": asdict(result),
        "event_types": event_types,
        "event_count": len(trace),
        "trace_sha256": _sha256(TRACE_JSONL),
        "database_sha256": _sha256(DATABASE),
        "checks": checks,
        "passed": passed,
    }
    _write_summary(summary, secret)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print("LIVE ACCEPTANCE PASSED" if passed else "LIVE ACCEPTANCE FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
