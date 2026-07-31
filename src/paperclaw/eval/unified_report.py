"""Machine-readable and Markdown reports for runtime evaluation runs."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from typing import Any, Sequence

from .contracts import EVALUATION_SCHEMA_VERSION, EvaluationCase, EvaluationResult


def write_unified_report(output: str | Path, cases: Sequence[EvaluationCase], results: Sequence[EvaluationResult], *, dataset: str | Path, paperclaw_version: str, mode: str, research_report: str | Path | None = None, retrieval_report: str | Path | None = None, enabled_evaluators: Sequence[str] = ("workflow", "tools", "reliability", "gate", "trace", "aggregate")) -> Path:
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    (target / "cases").mkdir(exist_ok=True)
    for name in ("workflow", "tools", "reliability", "citations", "human-gate"):
        (target / "failures" / name).mkdir(parents=True, exist_ok=True)
    (target / "traces").mkdir(exist_ok=True)
    dataset_path = Path(dataset)
    dataset_digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    actual_evaluators = list(enabled_evaluators)
    if research_report is not None:
        actual_evaluators.append("research")
    if retrieval_report is not None:
        actual_evaluators.append("retrieval")
    manifest = {
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "paperclaw_version": paperclaw_version,
        "commit_sha": _commit_sha(),
        "dataset": str(dataset_path),
        "dataset_digest": dataset_digest,
        "mode": mode,
        "started_at": now,
        "finished_at": now,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "provider": "fake/recorded" if mode == "offline" else "operator-supplied",
        "pricing_digest": None,
        "enabled_evaluators": actual_evaluators,
    }
    status_counts = Counter(result.status.value for result in results)
    failures = Counter(item.code for result in results for item in result.failures)
    research_payload = _load_optional_report(research_report, "paperclaw.research_eval")
    retrieval_payload = _load_optional_report(retrieval_report, "paperclaw.retrieval.quality_eval")
    aggregate_payload = {
        result.case_id: dict(result.metrics.get("aggregate", {}))
        for result in results
    }
    model_runs = [row for row in aggregate_payload.values() if int(row.get("model_calls", 0)) > 0]
    known_costs = [row["estimated_cost_usd"] for row in model_runs if row.get("estimated_cost_usd") is not None]
    tokens_known = bool(model_runs) and all(
        result.metrics.get("trace", {}).get("token_observation") == "known"
        for result in results
        if int(result.metrics.get("aggregate", {}).get("model_calls", 0)) > 0
    )
    unpriced_calls = sum(int(row.get("unpriced_model_calls", 0)) for row in model_runs)
    if not model_runs:
        cost_status = "unknown"
    elif unpriced_calls:
        cost_status = "partial" if known_costs else "unknown"
    else:
        cost_status = "known"
    cost_summary = {
        "estimated_cost": round(sum(known_costs), 12) if cost_status == "known" else None,
        "known_cost_subtotal": round(sum(known_costs), 12) if known_costs else None,
        "token_count": sum(int(row.get("total_tokens", 0)) for row in model_runs) if tokens_known else None,
        "unpriced_model_calls": unpriced_calls,
        "status": cost_status,
    }
    summary = {
        "case_totals": {"total": len(results), **dict(sorted(status_counts.items()))},
        "workflow_success_rate": round(sum(result.status.value in {"PASS", "WAITING_APPROVAL"} for result in results) / len(results), 6) if results else 0.0,
        "failure_distribution": dict(sorted(failures.items())),
        "workflow_metrics": _average_group(results, "workflow"),
        "tool_metrics": _average_group(results, "tools"),
        "reliability_metrics": _average_group(results, "reliability"),
        "gate_metrics": _average_group(results, "gate"),
        "retrieval_metrics": retrieval_payload,
        "research_metrics": research_payload,
        "citation_metrics": {"status": "NOT_VERIFIED without curated claim-support labels"},
        "cost": cost_summary,
    }
    _write_json(target / "manifest.json", manifest)
    _write_json(target / "summary.json", summary)
    _write_json(target / "aggregate-runtime.json", {"source": "paperclaw.eval.aggregate.evaluate_run_cost", "cases": aggregate_payload})
    _write_json(target / "research-eval.json", summary["research_metrics"])
    _write_json(target / "retrieval-quality.json", summary["retrieval_metrics"])
    _write_json(target / "traces" / "trace-reference.json", {result.case_id: {"run_id": result.run_id, "event_ids": list(result.trace_event_ids)} for result in results})
    for result in results:
        _write_json(target / "cases" / f"{result.case_id}.json", result.to_dict())
    (target / "report.md").write_text(_render_markdown(manifest, summary, results), encoding="utf-8")
    return target


def _average_group(results: Sequence[EvaluationResult], group: str) -> dict[str, Any]:
    rows = [result.metrics.get(group, {}) for result in results]
    keys = sorted({key for row in rows if isinstance(row, dict) for key in row})
    output: dict[str, Any] = {}
    for key in keys:
        values = [row[key] for row in rows if isinstance(row, dict) and isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)]
        booleans = [row[key] for row in rows if isinstance(row, dict) and isinstance(row.get(key), bool)]
        if values:
            output[key] = round(sum(values) / len(values), 6)
        elif booleans:
            output[key] = {"true": sum(booleans), "false": len(booleans) - sum(booleans)}
    return output


def _render_markdown(manifest: dict[str, Any], summary: dict[str, Any], results: Sequence[EvaluationResult]) -> str:
    lines = ["# PaperClaw Evaluation Report", "", f"- Commit: `{manifest['commit_sha']}`", f"- Mode: `{manifest['mode']}` ({'offline control-flow evaluation' if manifest['mode'] == 'offline' else manifest['mode']})", f"- Dataset digest: `{manifest['dataset_digest']}`", f"- Cases: {summary['case_totals']}", "", "## Case Results", "", "| Case | Status | Failures | Trace evidence |", "|---|---:|---|---|"]
    for result in results:
        lines.append(f"| `{result.case_id}` | {result.status.value} | {', '.join(item.code for item in result.failures) or '-'} | {', '.join(result.trace_event_ids[-3:]) or '-'} |")
    lines += ["", "## Boundaries", "", "- Offline recordings validate deterministic control flow; they are not real E2E or live-provider evidence.", "- WAITING_APPROVAL is a valid safety state, not ordinary task failure; no approval is fabricated.", "- Delivery metrics retain at-least-once semantics; no exactly-once claim is made.", "- Research and retrieval metrics are delegated to the existing evaluators; semantic citation correctness is NOT_VERIFIED without curated labels.", "- Token and cost are `unknown`, never coerced to zero, when provider usage is unavailable.", "- Live Provider, Redis/PostgreSQL distributed execution, and real human approval are not exercised by this report.", ""]
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_optional_report(path: str | Path | None, implementation: str) -> dict[str, Any]:
    if path is None:
        return {"status": "NOT_SUPPLIED", "implementation": implementation}
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{implementation} report must contain a JSON object")
    return {"status": "SUPPLIED", "implementation": implementation, "source": str(source), "report": payload}


def _commit_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


__all__ = ["write_unified_report"]
