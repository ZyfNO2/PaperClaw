from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.eval.benchmark_cli import main
from paperclaw.eval.case_loader import CaseValidationError, load_cases, parse_case
from paperclaw.eval.case_runner import run_case, run_cases
from paperclaw.eval.contracts import CaseStatus
from paperclaw.eval.contracts import EvaluationResult
from paperclaw.eval.runtime_adapter import RecordedTraceAdapter
from paperclaw.eval.unified_report import write_unified_report
from paperclaw.eval import AggregateEvalReport, EvalMetric


ROOT = Path(__file__).parents[3]
DATASET = ROOT / "examples" / "evaluation" / "runtime-cases.jsonl"


def _payload(**overrides):
    payload = {
        "schema_version": "1",
        "case_id": "case-1",
        "category": "workflow",
        "mode": "offline",
        "request": {"request_id": "request-1", "input": "do work"},
        "expectation": {"terminal_states": ["completed"]},
    }
    payload.update(overrides)
    return payload


def test_loads_versioned_dataset_and_defaults() -> None:
    cases = load_cases(DATASET)
    assert len(cases) == 15
    assert cases[0].schema_version == "1"
    assert cases[1].limits.max_steps == 20


@pytest.mark.parametrize(
    "change,match",
    [
        ({"schema_version": "2"}, "schema_version"),
        ({"unknown": True}, "unknown case field"),
        ({"mode": "magic"}, "unknown mode"),
        ({"expectation": {"terminal_states": ["invented"]}}, "unknown terminal"),
        ({"expectation": {"terminal_states": ["completed"], "required_roles": ["manager"]}}, "unknown role"),
    ],
)
def test_rejects_invalid_contract(change, match) -> None:
    with pytest.raises(CaseValidationError, match=match):
        parse_case(_payload(**change))


def test_digest_is_stable_across_mapping_order() -> None:
    left = parse_case(_payload())
    right_payload = dict(reversed(list(_payload().items())))
    right = parse_case(right_payload)
    assert left.digest() == right.digest()


def test_legacy_eval_exports_remain_available() -> None:
    assert AggregateEvalReport is not None
    assert EvalMetric is not None


@pytest.mark.parametrize(
    "plan",
    ["bad", [], {}, {"source": "x", "tasks": []}, {"tasks": []}, {"tasks": [{"task_id": "a", "extra": 1}]}],
)
def test_rejects_invalid_plan_contract(plan) -> None:
    with pytest.raises(CaseValidationError):
        parse_case(_payload(plan=plan))


def test_rejects_contradictory_tool_expectations() -> None:
    with pytest.raises(CaseValidationError, match="overlap"):
        parse_case(_payload(expectation={"terminal_states": ["completed"], "required_tools": ["shell"], "forbidden_tools": ["shell"]}))


def test_dataset_order_does_not_change_result_order() -> None:
    cases = load_cases(DATASET)[:3]
    adapter = RecordedTraceAdapter(ROOT)
    assert [item.case_id for item in run_cases(cases, adapter)] == [item.case_id for item in run_cases(tuple(reversed(cases)), adapter)]


def test_workflow_tool_and_trace_case_passes() -> None:
    case = next(item for item in load_cases(DATASET) if item.case_id == "workflow_coordinator_split_001")
    result = run_case(case, RecordedTraceAdapter(ROOT))
    assert result.status is CaseStatus.PASS
    assert result.metrics["workflow"]["plan_task_coverage"] == 1.0
    assert result.metrics["tools"]["required_tool_coverage"] == 1.0
    assert result.metrics["trace"]["trace_complete"] is True
    assert result.metrics["aggregate"]["run_id"] == "workflow-success"
    assert result.metrics["aggregate"]["estimated_cost_usd"] is None


def test_reviewer_rejection_is_followed_by_rework() -> None:
    case = next(item for item in load_cases(DATASET) if item.case_id == "workflow_reviewer_rework_001")
    metrics = run_case(case, RecordedTraceAdapter(ROOT)).metrics["workflow"]
    assert metrics["review_rework_count"] == 1
    assert metrics["reviewer_rejection_followed_by_rework"] is True
    assert metrics["review_loop_detected"] is False


def test_permission_denial_precedes_remote_side_effect() -> None:
    case = next(item for item in load_cases(DATASET) if item.case_id == "tool_permission_denial_001")
    result = run_case(case, RecordedTraceAdapter(ROOT))
    assert result.status is CaseStatus.PASS
    assert result.metrics["tools"]["permission_denial_count"] == 1
    assert result.metrics["tools"]["permission_bypass_count"] == 0
    assert result.metrics["tools"]["extension_policy_recheck_count"] == 1


def test_production_tool_payload_name_and_call_index_are_supported(tmp_path: Path) -> None:
    trace = tmp_path / "production.trace.jsonl"
    rows = [
        {"event_id": "p1", "sequence": 1, "occurred_at": "2026-08-01T00:00:00+00:00", "conversation_id": "c", "run_id": "p", "event_type": "run.started", "component": "harness", "payload": {"request_id": "request-1"}, "schema_version": 1},
        {"event_id": "p2", "sequence": 2, "occurred_at": "2026-08-01T00:00:01+00:00", "conversation_id": "c", "run_id": "p", "event_type": "tool.started", "component": "tool", "payload": {"tool": "paper_search", "call_index": 1}, "schema_version": 1},
        {"event_id": "p3", "sequence": 3, "occurred_at": "2026-08-01T00:00:02+00:00", "conversation_id": "c", "run_id": "p", "event_type": "tool.completed", "component": "tool", "payload": {"tool": "paper_search", "call_index": 1}, "schema_version": 1},
        {"event_id": "p4", "sequence": 4, "occurred_at": "2026-08-01T00:00:03+00:00", "conversation_id": "c", "run_id": "p", "event_type": "run.completed", "component": "harness", "payload": {}, "schema_version": 1},
    ]
    trace.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    case = parse_case(_payload(expectation={"terminal_states": ["completed"], "required_tools": ["paper_search"], "allowed_tools": ["paper_search"]}, metadata={"trace_fixture": "production.trace.jsonl"}))
    result = run_case(case, RecordedTraceAdapter(tmp_path))
    assert result.status is CaseStatus.PASS
    assert result.metrics["tools"]["required_tool_coverage"] == 1.0
    assert result.metrics["trace"]["unmatched_tool_call_count"] == 0


def test_retry_success_preserves_at_least_once_metrics() -> None:
    case = next(item for item in load_cases(DATASET) if item.case_id == "reliability_retry_success_001")
    result = run_case(case, RecordedTraceAdapter(ROOT))
    assert result.status is CaseStatus.PASS
    assert result.metrics["reliability"]["retry_count"] == 1
    assert result.metrics["reliability"]["retry_success_rate"] == 1.0


def test_waiting_approval_is_not_task_failure_and_no_action_executes() -> None:
    case = next(item for item in load_cases(DATASET) if item.case_id == "human_gate_external_write_001")
    result = run_case(case, RecordedTraceAdapter(ROOT))
    assert result.status is CaseStatus.WAITING_APPROVAL
    assert result.failures == ()
    assert result.metrics["gate"]["expected_gate_triggered"] is True
    assert result.metrics["gate"]["protected_action_executed_after_waiting"] is False


def test_read_only_case_does_not_false_positive_gate() -> None:
    case = next(item for item in load_cases(DATASET) if item.case_id == "human_gate_read_no_false_positive_001")
    result = run_case(case, RecordedTraceAdapter(ROOT))
    assert result.status is CaseStatus.PASS
    assert result.metrics["gate"]["unexpected_gate"] is False


def test_wrong_gate_reason_is_a_failure(tmp_path: Path) -> None:
    source = ROOT / "examples" / "evaluation" / "traces" / "human-gate.trace.jsonl"
    case = parse_case(_payload(request={"request_id": "eval-gate", "input": "write"}, expectation={"terminal_states": ["waiting_approval"], "expected_gate": {"required": True, "action_type": "external_write", "reason_code": "wrong"}}, metadata={"trace_fixture": source.name}))
    (tmp_path / source.name).write_bytes(source.read_bytes())
    result = run_case(case, RecordedTraceAdapter(tmp_path))
    assert result.status is CaseStatus.FAIL
    assert any(item.code == "MISSING_GATE" for item in result.failures)


def test_unified_report_is_json_serializable_and_unknown_cost_remains_null(tmp_path: Path) -> None:
    cases = load_cases(DATASET)[:2]
    results = run_cases(cases, RecordedTraceAdapter(ROOT))
    output = write_unified_report(tmp_path / "report", cases, results, dataset=DATASET, paperclaw_version="test", mode="offline")
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["cost"]["estimated_cost"] is None
    assert summary["cost"]["token_count"] is None
    assert (output / "report.md").is_file()
    assert (output / "traces" / "trace-reference.json").is_file()
    aggregate = json.loads((output / "aggregate-runtime.json").read_text(encoding="utf-8"))
    assert aggregate["source"] == "paperclaw.eval.aggregate.evaluate_run_cost"


def test_unified_report_embeds_existing_research_and_retrieval_reports(tmp_path: Path) -> None:
    cases = load_cases(DATASET)[:1]
    results = run_cases(cases, RecordedTraceAdapter(ROOT))
    research = tmp_path / "research.json"
    retrieval = tmp_path / "retrieval.json"
    research.write_text('{"case_count": 1}', encoding="utf-8")
    retrieval.write_text('{"mean_mrr": 1.0}', encoding="utf-8")
    output = write_unified_report(tmp_path / "report", cases, results, dataset=DATASET, paperclaw_version="test", mode="offline", research_report=research, retrieval_report=retrieval)
    assert json.loads((output / "research-eval.json").read_text(encoding="utf-8"))["status"] == "SUPPLIED"
    assert json.loads((output / "retrieval-quality.json").read_text(encoding="utf-8"))["report"]["mean_mrr"] == 1.0


def test_unknown_model_tokens_never_become_zero(tmp_path: Path) -> None:
    case = parse_case(_payload())
    result = EvaluationResult(
        case_id=case.case_id,
        case_digest=case.digest(),
        run_id="run",
        status=CaseStatus.PASS,
        metrics={
            "aggregate": {"model_calls": 1, "total_tokens": 0, "estimated_cost_usd": None, "unpriced_model_calls": 1},
            "trace": {"token_observation": "unknown"},
        },
    )
    output = write_unified_report(tmp_path / "report", [case], [result], dataset=DATASET, paperclaw_version="test", mode="live")
    cost = json.loads((output / "summary.json").read_text(encoding="utf-8"))["cost"]
    assert cost["token_count"] is None
    assert cost["estimated_cost"] is None
    assert cost["status"] == "unknown"


def test_cli_continues_and_writes_all_case_results(tmp_path: Path) -> None:
    output = tmp_path / "cli"
    assert main(["--dataset", str(DATASET), "--workspace", str(ROOT), "--output", str(output)]) == 0
    assert len(list((output / "cases").glob("*.json"))) == 15


def test_failure_points_to_trace_evidence() -> None:
    payload = _payload(
        request={"request_id": "eval-workflow", "input": "mismatch terminal"},
        expectation={"terminal_states": ["failed"]},
        metadata={"trace_fixture": "examples/evaluation/traces/workflow-success.trace.jsonl"},
    )
    result = run_case(parse_case(payload), RecordedTraceAdapter(ROOT))
    assert result.status is CaseStatus.FAIL
    assert result.failures[0].code == "WRONG_TERMINAL_STATE"
    assert result.failures[0].evidence_event_ids


def test_fixture_path_cannot_escape_workspace() -> None:
    case = parse_case(_payload(metadata={"trace_fixture": "../outside.trace.jsonl"}))
    result = run_case(case, RecordedTraceAdapter(ROOT))
    assert result.status is CaseStatus.FAIL
    assert "inside workspace" in result.failures[0].message
