"""Variant execution, plugin registries and deterministic report rendering."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .contracts import (
    REPORT_SCHEMA,
    CaseResult,
    EvalCase,
    EvidenceHit,
    canonical_digest,
    sanitize_metadata,
)
from .metrics import CaseScore, MetricRegistry, aggregate_scores


class EvaluationVariant(Protocol):
    variant_id: str
    version: str

    def run(self, case: EvalCase) -> CaseResult: ...


class RetrievalVariant(Protocol):
    variant_id: str
    version: str

    def retrieve(self, case: EvalCase, *, limit: int) -> Sequence[EvidenceHit]: ...


class CapabilityProvider(Protocol):
    provider_id: str
    version: str

    def capabilities(self) -> Sequence[str]: ...

    def invoke(
        self, capability_id: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


class ReportRenderer(Protocol):
    renderer_id: str
    version: str

    def render(self, report: Mapping[str, Any]) -> str: ...


class RecordedVariant:
    version = "recorded-v1"

    def __init__(
        self,
        variant_id: str,
        results: Mapping[str, CaseResult],
    ) -> None:
        self.variant_id = variant_id
        self._results = dict(results)

    def run(self, case: EvalCase) -> CaseResult:
        try:
            result = self._results[case.case_id]
        except KeyError as exc:
            raise KeyError(f"missing recorded result for {case.case_id}") from exc
        if result.variant_id != self.variant_id:
            raise ValueError("recorded result variant mismatch")
        return result


class StaticRegistry:
    """Explicit plugin registry with duplicate-ID rejection."""

    def __init__(self, plugins: Sequence[object], *, id_attribute: str) -> None:
        plugins_tuple = tuple(plugins)
        mapping = {
            str(getattr(plugin, id_attribute)): plugin for plugin in plugins_tuple
        }
        if len(mapping) != len(plugins_tuple):
            raise ValueError(f"duplicate {id_attribute}")
        self._plugins = mapping

    def get(self, plugin_id: str) -> object:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {plugin_id}") from exc

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))


@dataclass(frozen=True)
class VariantReport:
    variant_id: str
    version: str
    case_results: tuple[CaseResult, ...]
    scores: tuple[CaseScore, ...]
    aggregate: Mapping[str, float]
    failures: tuple[Mapping[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "version": self.version,
            "case_results": [result.to_dict() for result in self.case_results],
            "scores": [score.to_dict() for score in self.scores],
            "aggregate": dict(sorted(self.aggregate.items())),
            "failures": [dict(item) for item in self.failures],
        }


class EvaluationRunner:
    def __init__(
        self,
        variants: Sequence[EvaluationVariant],
        *,
        metrics: MetricRegistry | None = None,
    ) -> None:
        self._variants = tuple(variants)
        ids = [variant.variant_id for variant in self._variants]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evaluation variant_id")
        self._metrics = metrics or MetricRegistry()

    def run(
        self,
        cases: Sequence[EvalCase],
        *,
        dataset_digest: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        variant_reports: list[VariantReport] = []
        for variant in self._variants:
            results: list[CaseResult] = []
            scores: list[CaseScore] = []
            failures: list[Mapping[str, str]] = []
            for case in cases:
                try:
                    result = variant.run(case)
                except Exception as exc:
                    result = CaseResult(
                        case_id=case.case_id,
                        variant_id=variant.variant_id,
                        status="failed",
                        error={
                            "error_type": type(exc).__name__,
                            "message": str(exc)[:500],
                        },
                    )
                    failures.append(
                        {
                            "case_id": case.case_id,
                            "error_type": type(exc).__name__,
                            "message": str(exc)[:500],
                        }
                    )
                results.append(result)
                scores.append(self._metrics.score(case, result))
            variant_reports.append(
                VariantReport(
                    variant_id=variant.variant_id,
                    version=variant.version,
                    case_results=tuple(results),
                    scores=tuple(scores),
                    aggregate=aggregate_scores(scores),
                    failures=tuple(failures),
                )
            )
        report = {
            "schema": REPORT_SCHEMA,
            "dataset_digest": dataset_digest,
            "case_count": len(cases),
            "variants": [item.to_dict() for item in variant_reports],
            "metadata": sanitize_metadata(metadata or {}),
        }
        report["report_digest"] = canonical_digest(report)
        return report


class JsonReportRenderer:
    renderer_id = "json"
    version = "1"

    def render(self, report: Mapping[str, Any]) -> str:
        return json.dumps(
            report, sort_keys=True, indent=2, ensure_ascii=False
        ) + "\n"


class MarkdownReportRenderer:
    renderer_id = "markdown"
    version = "1"

    def render(self, report: Mapping[str, Any]) -> str:
        lines = [
            "# PaperClaw Research Evaluation",
            "",
            f"- Dataset digest: `{report['dataset_digest']}`",
            f"- Report digest: `{report['report_digest']}`",
            f"- Cases: {report['case_count']}",
            "",
        ]
        for variant in report["variants"]:
            lines.extend(
                [
                    f"## {variant['variant_id']}",
                    "",
                    f"- Version: `{variant['version']}`",
                    f"- Failed cases: {len(variant['failures'])}",
                    "",
                    "| Metric | Mean |",
                    "|---|---:|",
                ]
            )
            for metric_id, value in variant["aggregate"].items():
                lines.append(f"| {metric_id} | {value:.6f} |")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def write_report(
    report: Mapping[str, Any],
    path: str | Path,
    *,
    renderer: ReportRenderer | None = None,
) -> None:
    resolved = renderer or JsonReportRenderer()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(resolved.render(report), encoding="utf-8")


def compare_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for report in reports:
        for variant in report.get("variants", []):
            rows.append(
                {
                    "dataset_digest": report.get("dataset_digest"),
                    "report_digest": report.get("report_digest"),
                    "variant_id": variant.get("variant_id"),
                    "version": variant.get("version"),
                    "aggregate": variant.get("aggregate", {}),
                    "failure_count": len(variant.get("failures", [])),
                }
            )
    output = {
        "schema": "paperclaw.research-eval.compare.v1",
        "rows": sorted(
            rows,
            key=lambda item: (
                str(item["variant_id"]),
                str(item["report_digest"]),
            ),
        ),
    }
    output["compare_digest"] = canonical_digest(output)
    return output
