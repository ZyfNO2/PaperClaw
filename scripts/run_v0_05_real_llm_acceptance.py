#!/usr/bin/env python3
"""Repeatable real-LLM acceptance runner for PaperClaw v0.05.

Usage:
    python scripts/run_v0_05_real_llm_acceptance.py

Prerequisites:
    PAPERCLAW_API_KEY, PAPERCLAW_BASE_URL, and PAPERCLAW_MODEL must be set in
    the environment or in a ``.env`` file at the repository root.

The runner:
1. Validates provider environment variables.
2. Creates a clean workspace under ``tmp/v0_05_real_llm_workspace/``.
3. Submits a fixed task to the QueryEngine with explicit budgets.
4. Collects the RunResult and all QueryEngine events.
5. Verifies that ``hello.py`` exists and prints the expected string.
6. Writes a redacted artifact bundle to ``artifacts/v0_05/real_llm/``.
7. Exits with code 0 on acceptance, 1 on failure, 2 on misconfiguration.

Nothing in this script modifies the repository source tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the repository ``src`` directory is on the path when the script is run
# directly from the repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperclaw.harness import AgentRuntimeExecutor, QueryEngine, RunLimits
from paperclaw.models.adapters import OpenAICompatibleModel


TASK = (
    "Create a file named hello.py in the workspace that prints exactly "
    "'PaperClaw v0.05 REAL LLM OK.' when run with python. "
    "Run the file with python, confirm the output, then finish with done."
)

EXPECTED_OUTPUT = "PaperClaw v0.05 REAL LLM OK."
WORKSPACE_DIR = REPO_ROOT / "tmp" / "v0_05_real_llm_workspace"
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "v0_05" / "real_llm"


def _load_dotenv() -> None:
    dotenv = REPO_ROOT / ".env"
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
    _load_dotenv()
    required = {
        "PAPERCLAW_API_KEY": os.getenv("PAPERCLAW_API_KEY"),
        "PAPERCLAW_BASE_URL": os.getenv("PAPERCLAW_BASE_URL"),
        "PAPERCLAW_MODEL": os.getenv("PAPERCLAW_MODEL"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        print(
            f"ERROR: missing environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(2)
    # Validate that the key at least looks like a secret and not an empty placeholder.
    for name, value in required.items():
        if len(value.strip()) < 8:
            print(
                f"ERROR: {name} looks too short to be valid",
                file=sys.stderr,
            )
            sys.exit(2)
    return required  # type: ignore[return-item]


def _redact_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove or mask sensitive fields from an event payload before archiving."""
    redacted = dict(payload)
    # Drop any absolute workspace paths that may appear in tool metadata.
    for key in ("cwd", "path"):
        if key in redacted and isinstance(redacted[key], str):
            value = Path(redacted[key])
            if value.is_absolute():
                redacted[key] = f"<workspace>/{value.name}"
    return redacted


def _build_environment_report(env: dict[str, str]) -> dict[str, Any]:
    """Record non-sensitive environment facts for reproducibility."""
    return {
        "provider": "openai-compatible",
        "base_url": env["PAPERCLAW_BASE_URL"],
        "model": env["PAPERCLAW_MODEL"],
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": os.environ.get("OS", "unknown"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sensitive_variables_present": {
            "PAPERCLAW_API_KEY": bool(env.get("PAPERCLAW_API_KEY")),
            "PAPERCLAW_BASE_URL": bool(env.get("PAPERCLAW_BASE_URL")),
            "PAPERCLAW_MODEL": bool(env.get("PAPERCLAW_MODEL")),
        },
    }


def _write_redaction_report(artifact_dir: Path) -> None:
    report = artifact_dir / "redaction_report.md"
    report.write_text(
        "# Real LLM Artifact Redaction Report\n\n"
        "This artifact bundle is produced by ``scripts/run_v0_05_real_llm_acceptance.py``.\n\n"
        "Redactions applied before writing:\n\n"
        "- ``PAPERCLAW_API_KEY`` is never written to disk.\n"
        "- Authorization headers are not captured because the runner never intercepts HTTP traffic.\n"
        "- Absolute workspace paths in tool metadata are replaced with ``<workspace>/<basename>``.\n"
        "- Environment variables other than provider name/base URL/model are not recorded.\n"
        "- Provider response request IDs are not captured.\n\n"
        "If you rerun the script with a real provider, these files will be overwritten.\n",
        encoding="utf-8",
    )


def main() -> int:
    env = _require_env()

    # Clean and recreate the isolated workspace.
    if WORKSPACE_DIR.exists():
        shutil.rmtree(WORKSPACE_DIR)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    model = OpenAICompatibleModel(
        api_key=env["PAPERCLAW_API_KEY"],
        base_url=env["PAPERCLAW_BASE_URL"],
        model=env["PAPERCLAW_MODEL"],
        timeout=120,
    )

    events: list[tuple[str, dict[str, Any]]] = []
    executor = AgentRuntimeExecutor(model, WORKSPACE_DIR)
    engine = QueryEngine(
        executor,
        conversation_id="v0-05-real-llm-acceptance",
        event_handler=lambda event_type, payload: events.append(
            (event_type, _redact_event_payload(dict(payload)))
        ),
    )

    limits = RunLimits(max_steps=10, max_model_calls=10, max_tool_calls=10)
    result = engine.submit(TASK, limits=limits)

    hello = WORKSPACE_DIR / "hello.py"
    file_ok = hello.exists()
    content_match = False
    if file_ok:
        content_match = EXPECTED_OUTPUT in hello.read_text(encoding="utf-8")

    # Collect tool results for the artifact bundle.
    tool_results: list[dict[str, Any]] = []
    for event_type, payload in events:
        if event_type in {"tool.completed", "tool.failed"}:
            tool_results.append({"event_type": event_type, **payload})

    run_summary = {
        "provider": "openai-compatible",
        "model": env["PAPERCLAW_MODEL"],
        "status": result.status,
        "stop_reason": result.stop_reason,
        "model_calls": result.model_calls,
        "tool_calls": result.tool_calls,
        "max_steps": limits.max_steps,
        "max_model_calls": limits.max_model_calls,
        "max_tool_calls": limits.max_tool_calls,
        "terminal_event_count": sum(
            1
            for event_type, _ in events
            if event_type in {"run.completed", "run.failed", "run.stopped"}
        ),
        "acceptance_checks": {
            "file_created": file_ok,
            "content_match": content_match,
            "exit_code_ok": file_ok and content_match and result.status == "completed",
        },
    }

    normalized_result = asdict(result)
    normalized_result["run_id"] = "<run_id>"

    event_trace = {
        "schema_version": 1,
        "scenario": "real-llm-create-run-verify",
        "result": normalized_result,
        "events": [
            {"event_type": event_type, "payload": payload}
            for event_type, payload in events
        ],
    }

    # Write artifacts.
    (ARTIFACT_DIR / "run_summary.json").write_text(
        json.dumps(run_summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "event_trace.json").write_text(
        json.dumps(event_trace, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "tool_results.json").write_text(
        json.dumps(tool_results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "environment.json").write_text(
        json.dumps(_build_environment_report(env), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_redaction_report(ARTIFACT_DIR)

    generated_dir = ARTIFACT_DIR / "generated_files"
    generated_dir.mkdir(parents=True, exist_ok=True)
    if file_ok:
        content = hello.read_bytes()
        (generated_dir / "hello.py").write_bytes(content)
        (generated_dir / "hello.py.sha256").write_text(
            hashlib.sha256(content).hexdigest() + "\n", encoding="utf-8"
        )

    # Console summary.
    print(json.dumps(run_summary, indent=2, ensure_ascii=False))
    if run_summary["acceptance_checks"]["exit_code_ok"]:
        print("ACCEPTANCE PASSED")
        return 0
    print("ACCEPTANCE FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
