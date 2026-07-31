"""Versioned contracts for repeatable runtime evaluation cases and results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Mapping

from paperclaw.multiagent.contracts import AgentRole, TaskStatus

EVALUATION_SCHEMA_VERSION = "1"


class CaseStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    NOT_EXECUTED = "NOT_EXECUTED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    NOT_VERIFIED = "NOT_VERIFIED"
    PENDING = "PENDING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class GateExpectation:
    required: bool
    action_type: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class CaseExpectation:
    terminal_states: tuple[str, ...]
    required_roles: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    required_output_fields: tuple[str, ...] = ()
    expected_gate: GateExpectation | None = None


@dataclass(frozen=True)
class CaseLimits:
    max_steps: int = 20
    max_tool_calls: int = 12
    max_retries: int = 3
    timeout_seconds: int = 120
    loop_window: int = 3


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    category: str
    mode: str
    request: Mapping[str, Any]
    expectation: CaseExpectation
    limits: CaseLimits = field(default_factory=CaseLimits)
    plan: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EVALUATION_SCHEMA_VERSION

    def digest(self) -> str:
        raw = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvaluationFailure:
    code: str
    case_id: str
    run_id: str | None
    role: str | None
    step_index: int | None
    message: str
    evidence_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_event_ids"] = list(self.evidence_event_ids)
        return data


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    case_digest: str
    run_id: str | None
    status: CaseStatus
    metrics: Mapping[str, Any]
    failures: tuple[EvaluationFailure, ...] = ()
    trace_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_digest": self.case_digest,
            "run_id": self.run_id,
            "status": self.status.value,
            "metrics": dict(self.metrics),
            "failures": [item.to_dict() for item in self.failures],
            "trace_event_ids": list(self.trace_event_ids),
        }


VALID_TERMINAL_STATES = frozenset(item.value for item in TaskStatus) | {"waiting_approval", "stopped"}
VALID_ROLES = frozenset(item.value for item in AgentRole)
VALID_MODES = frozenset({"offline", "local", "live", "distributed"})


__all__ = [
    "CaseExpectation", "CaseLimits", "CaseStatus", "EVALUATION_SCHEMA_VERSION",
    "EvaluationCase", "EvaluationFailure", "EvaluationResult", "GateExpectation",
    "VALID_MODES", "VALID_ROLES", "VALID_TERMINAL_STATES",
]
