"""Versioned dataset and result contracts for repository research evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

DATASET_SCHEMA = "paperclaw.research-eval.dataset.v1"
RESULT_SCHEMA = "paperclaw.research-eval.result.v1"
REPORT_SCHEMA = "paperclaw.research-eval.report.v1"


@dataclass(frozen=True)
class EvidenceExpectation:
    source_id: str
    required_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(
            self,
            "required_terms",
            tuple(_required_text(term, "required_term") for term in self.required_terms),
        )


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    question: str
    workspace_fixture: str
    expected_evidence: tuple[EvidenceExpectation, ...] = ()
    required_claims: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        object.__setattr__(self, "question", _required_text(self.question, "question"))
        object.__setattr__(
            self,
            "workspace_fixture",
            _required_text(self.workspace_fixture, "workspace_fixture"),
        )
        object.__setattr__(
            self,
            "required_claims",
            tuple(_required_text(value, "required_claim") for value in self.required_claims),
        )
        object.__setattr__(
            self,
            "forbidden_claims",
            tuple(_required_text(value, "forbidden_claim") for value in self.forbidden_claims),
        )
        object.__setattr__(
            self,
            "tags",
            tuple(_identifier(value, "tag") for value in self.tags),
        )


@dataclass(frozen=True)
class EvidenceHit:
    source_id: str
    rank: int
    score: float = 0.0
    excerpt: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        object.__setattr__(self, "excerpt", _bounded_text(self.excerpt))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True)
class EvaluatedClaim:
    text: str
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _required_text(self.text, "claim text"))
        object.__setattr__(
            self,
            "source_ids",
            tuple(_identifier(value, "claim source_id") for value in self.source_ids),
        )


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    variant_id: str
    status: str
    hits: tuple[EvidenceHit, ...] = ()
    claims: tuple[EvaluatedClaim, ...] = ()
    model_calls: int = 0
    tool_calls: int = 0
    mcp_calls: int = 0
    latency_ms: float = 0.0
    selected_context_items: int = 0
    error: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        object.__setattr__(self, "variant_id", _identifier(self.variant_id, "variant_id"))
        if self.status not in {"completed", "failed", "skipped", "blocked"}:
            raise ValueError(f"invalid case result status: {self.status}")
        for name, value in (
            ("model_calls", self.model_calls),
            ("tool_calls", self.tool_calls),
            ("mcp_calls", self.mcp_calls),
            ("selected_context_items", self.selected_context_items),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        object.__setattr__(
            self, "error", sanitize_metadata(self.error) if self.error else None
        )
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "case_id": self.case_id,
            "variant_id": self.variant_id,
            "status": self.status,
            "hits": [
                {
                    "source_id": hit.source_id,
                    "rank": hit.rank,
                    "score": hit.score,
                    "excerpt": hit.excerpt,
                    "metadata": dict(hit.metadata),
                }
                for hit in self.hits
            ],
            "claims": [
                {"text": claim.text, "source_ids": list(claim.source_ids)}
                for claim in self.claims
            ],
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "mcp_calls": self.mcp_calls,
            "latency_ms": self.latency_ms,
            "selected_context_items": self.selected_context_items,
            "error": dict(self.error) if self.error else None,
            "metadata": dict(self.metadata),
        }


def load_dataset(path: str | Path) -> tuple[tuple[EvalCase, ...], str]:
    rows = _load_jsonl(path)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    canonical_rows: list[dict[str, Any]] = []
    for row in rows:
        schema = row.get("schema", DATASET_SCHEMA)
        if schema != DATASET_SCHEMA:
            raise ValueError(f"unsupported dataset schema: {schema}")
        expectations = tuple(
            EvidenceExpectation(
                source_id=item["source_id"],
                required_terms=tuple(item.get("required_terms", ())),
            )
            for item in _object_list(
                row.get("expected_evidence", []), "expected_evidence"
            )
        )
        case = EvalCase(
            case_id=row["case_id"],
            question=row["question"],
            workspace_fixture=row["workspace_fixture"],
            expected_evidence=expectations,
            required_claims=tuple(_string_list(row.get("required_claims", []), "required_claims")),
            forbidden_claims=tuple(_string_list(row.get("forbidden_claims", []), "forbidden_claims")),
            tags=tuple(_string_list(row.get("tags", []), "tags")),
        )
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
        canonical_rows.append(case_to_dict(case))
    return tuple(cases), canonical_digest(canonical_rows)


def load_recorded_results(
    path: str | Path, *, variant_id: str
) -> dict[str, CaseResult]:
    output: dict[str, CaseResult] = {}
    for row in _load_jsonl(path):
        row_variant = row.get("variant_id", variant_id)
        if row_variant != variant_id:
            raise ValueError(
                f"result variant mismatch: expected {variant_id}, got {row_variant}"
            )
        hits = tuple(
            EvidenceHit(
                source_id=item["source_id"],
                rank=item["rank"],
                score=float(item.get("score", 0.0)),
                excerpt=item.get("excerpt"),
                metadata=item.get("metadata", {}),
            )
            for item in _object_list(row.get("hits", []), "hits")
        )
        claims = tuple(
            EvaluatedClaim(
                text=item["text"],
                source_ids=tuple(
                    _string_list(item.get("source_ids", []), "source_ids")
                ),
            )
            for item in _object_list(row.get("claims", []), "claims")
        )
        result = CaseResult(
            case_id=row["case_id"],
            variant_id=variant_id,
            status=row.get("status", "completed"),
            hits=hits,
            claims=claims,
            model_calls=int(row.get("model_calls", 0)),
            tool_calls=int(row.get("tool_calls", 0)),
            mcp_calls=int(row.get("mcp_calls", 0)),
            latency_ms=float(row.get("latency_ms", 0.0)),
            selected_context_items=int(row.get("selected_context_items", 0)),
            error=row.get("error"),
            metadata=row.get("metadata", {}),
        )
        if result.case_id in output:
            raise ValueError(f"duplicate result case_id: {result.case_id}")
        output[result.case_id] = result
    return output


def case_to_dict(case: EvalCase) -> dict[str, Any]:
    return {
        "schema": DATASET_SCHEMA,
        "case_id": case.case_id,
        "question": case.question,
        "workspace_fixture": case.workspace_fixture,
        "expected_evidence": [
            {
                "source_id": item.source_id,
                "required_terms": list(item.required_terms),
            }
            for item in case.expected_evidence
        ],
        "required_claims": list(case.required_claims),
        "forbidden_claims": list(case.forbidden_claims),
        "tags": list(case.tags),
    }


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sanitize_metadata(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:100]:
            key = str(raw_key)[:100]
            normalized = key.lower().replace("-", "_")
            if any(
                marker in normalized
                for marker in (
                    "api_key",
                    "authorization",
                    "password",
                    "secret",
                    "credential",
                )
            ):
                continue
            output[key] = sanitize_metadata(raw_value, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            sanitize_metadata(item, depth=depth + 1)
            for item in list(value)[:100]
        ]
    return _bounded_text(str(value))


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL line {line_number} must be an object")
        rows.append(value)
    if not rows:
        raise ValueError("JSONL input must contain at least one record")
    return rows


def _object_list(value: Any, name: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} items must be objects")
    return value


def _string_list(value: Any, name: str) -> Sequence[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return value


def _identifier(value: str, name: str) -> str:
    normalized = _required_text(value, name)
    if len(normalized) > 200 or any(char.isspace() for char in normalized):
        raise ValueError(f"{name} must be a compact identifier")
    return normalized


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _bounded_text(value: str | None, limit: int = 4_000) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit] + "...<truncated>"
