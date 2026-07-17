from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.research_eval import (
    CaseResult,
    EvalCase,
    EvaluatedClaim,
    EvaluationRunner,
    EvidenceExpectation,
    EvidenceHit,
    MetricRegistry,
    MetricResult,
    RecordedVariant,
    load_dataset,
    load_recorded_results,
)
from paperclaw.research_eval.cli import main as cli_main

FIXTURES = Path(__file__).parents[2] / "fixtures" / "research_eval"


class RaisingMetric:
    metric_id = "raising_metric"
    version = "1"

    def evaluate(self, case, result):
        raise RuntimeError("metric failed")


class ConstantMetric:
    metric_id = "constant_metric"
    version = "1"

    def evaluate(self, case, result):
        return MetricResult(self.metric_id, 0.5, {"version": self.version})


def test_dataset_digest_and_recorded_results_are_deterministic():
    dataset_path = FIXTURES / "canonical_dataset.jsonl"
    first_cases, first_digest = load_dataset(dataset_path)
    second_cases, second_digest = load_dataset(dataset_path)
    assert first_cases == second_cases
    assert first_digest == second_digest
    assert len(first_cases) == 2

    results = load_recorded_results(
        FIXTURES / "canonical_results_bm25_mcp_verify.jsonl",
        variant_id="bm25_mcp_verify",
    )
    assert set(results) == {"repo-architecture-001", "repo-status-001"}
    assert "must-not-persist" not in repr(results)


def test_core_metrics_and_metric_plugins():
    case = EvalCase(
        case_id="case-1",
        question="question",
        workspace_fixture="fixture://one",
        expected_evidence=(
            EvidenceExpectation("source-a"),
            EvidenceExpectation("source-b"),
        ),
        required_claims=("alpha", "beta"),
        forbidden_claims=("fabricated",),
    )
    result = CaseResult(
        case_id="case-1",
        variant_id="variant-1",
        status="completed",
        hits=(
            EvidenceHit("source-a", 1),
            EvidenceHit("source-b", 3),
        ),
        claims=(
            EvaluatedClaim("Alpha is verified.", ("source-a",)),
            EvaluatedClaim("Beta is verified.", ("source-b",)),
        ),
        model_calls=2,
        tool_calls=1,
        mcp_calls=1,
        latency_ms=25,
        selected_context_items=2,
    )
    score = MetricRegistry([ConstantMetric(), RaisingMetric()]).score(case, result)
    assert score.metrics["recall_at_k"].value == 1.0
    assert score.metrics["mrr"].value == 1.0
    assert score.metrics["required_claim_coverage"].value == 1.0
    assert score.metrics["forbidden_claim_rate"].value == 0.0
    assert score.metrics["citation_correctness"].value == 1.0
    assert score.metrics["citation_completeness"].value == 1.0
    assert score.metrics["unsupported_claim_rate"].value == 0.0
    assert score.metrics["constant_metric"].value == 0.5
    assert score.plugin_failures[0]["metric_id"] == "raising_metric"


def test_runner_preserves_missing_case_failure():
    cases, digest = load_dataset(FIXTURES / "canonical_dataset.jsonl")
    recorded = load_recorded_results(
        FIXTURES / "canonical_results_bm25_mcp_verify.jsonl",
        variant_id="bm25_mcp_verify",
    )
    recorded.pop("repo-status-001")
    report = EvaluationRunner(
        [RecordedVariant("bm25_mcp_verify", recorded)]
    ).run(cases, dataset_digest=digest)
    variant = report["variants"][0]
    assert len(variant["case_results"]) == 2
    failed = next(
        result
        for result in variant["case_results"]
        if result["case_id"] == "repo-status-001"
    )
    assert failed["status"] == "failed"
    assert variant["failures"][0]["case_id"] == "repo-status-001"


def test_cli_generates_json_markdown_and_comparison(tmp_path):
    dataset = FIXTURES / "canonical_dataset.jsonl"
    strong_results = FIXTURES / "canonical_results_bm25_mcp_verify.jsonl"
    baseline_results = FIXTURES / "canonical_results_baseline_no_retrieval.jsonl"
    strong_json = tmp_path / "strong.json"
    strong_md = tmp_path / "strong.md"
    baseline_json = tmp_path / "baseline.json"
    comparison = tmp_path / "comparison.json"

    assert cli_main(
        [
            "run",
            "--dataset",
            str(dataset),
            "--results",
            str(strong_results),
            "--variant",
            "bm25_mcp_verify",
            "--output",
            str(strong_json),
            "--markdown",
            str(strong_md),
        ]
    ) == 0
    assert cli_main(
        [
            "run",
            "--dataset",
            str(dataset),
            "--results",
            str(baseline_results),
            "--variant",
            "baseline_no_retrieval",
            "--output",
            str(baseline_json),
        ]
    ) == 0
    assert cli_main(
        [
            "compare",
            "--input",
            str(strong_json),
            "--input",
            str(baseline_json),
            "--output",
            str(comparison),
        ]
    ) == 0

    strong = json.loads(strong_json.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
    compared = json.loads(comparison.read_text(encoding="utf-8"))
    assert strong["report_digest"]
    assert baseline["report_digest"]
    assert strong["variants"][0]["aggregate"]["recall_at_k"] == 1.0
    assert baseline["variants"][0]["aggregate"]["recall_at_k"] == 0.0
    assert "PaperClaw Research Evaluation" in strong_md.read_text(encoding="utf-8")
    assert len(compared["rows"]) == 2


def test_invalid_duplicate_case_id_is_rejected(tmp_path):
    line = (FIXTURES / "canonical_dataset.jsonl").read_text(encoding="utf-8").splitlines()[0]
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate case_id"):
        load_dataset(duplicate)
