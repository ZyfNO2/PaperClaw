"""Bounded semantic acceptance for completed Worker outputs.

Deterministic verification remains authoritative for locally checkable facts. This
module only answers the separate question: does the compact Worker result satisfy
the explicit task objective and acceptance criteria? It never upgrades failed
deterministic evidence and never receives permission to execute tools.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from paperclaw.agent.verification import VerificationResult
from paperclaw.models.base import ChatModel
from paperclaw.models.reliability import ProviderError

from .contracts import AgentTask, SemanticJudgeResult


@dataclass(frozen=True)
class SemanticJudgePolicy:
    """Strict upper bound for one semantic acceptance decision."""

    max_attempts: int = 2

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= 2:
            raise ValueError("max_attempts must be an integer in [1, 2]")


class SemanticAcceptanceJudge:
    """Judge acceptance criteria without changing deterministic evidence.

    A first rejection is never sufficient for a hard rejection. When the attempt
    budget allows it, the rejection is independently confirmed once. Two semantic
    rejections produce ``rejected``; reject/pass disagreement produces
    ``inconclusive``. Retriable provider failures may consume the remaining attempt
    budget, but a later lone rejection then remains ``inconclusive`` rather than
    being misclassified as a confirmed business failure.
    """

    def __init__(
        self,
        model: ChatModel,
        *,
        policy: SemanticJudgePolicy | None = None,
    ) -> None:
        self._model = model
        self._policy = policy or SemanticJudgePolicy()

    def evaluate(
        self,
        task: AgentTask,
        *,
        worker_summary: str,
        deterministic_result: VerificationResult | None,
        changed_files: list[str],
        unresolved_items: list[str],
    ) -> SemanticJudgeResult:
        attempts = 0
        first_rejection: tuple[str, str] | None = None

        while attempts < self._policy.max_attempts:
            attempts += 1
            try:
                turn = self._model.complete(
                    _build_prompt(
                        task,
                        worker_summary=worker_summary,
                        deterministic_result=deterministic_result,
                        changed_files=changed_files,
                        unresolved_items=unresolved_items,
                    )
                )
            except ProviderError as exc:
                if exc.retriable and attempts < self._policy.max_attempts:
                    continue
                status = "transient_error" if exc.retriable else "provider_error"
                return self._result(
                    status,
                    reason_code=exc.code.lower(),
                    summary=str(exc),
                    attempt_count=attempts,
                    transient=exc.retriable,
                )
            except Exception as exc:  # defensive adapter boundary
                return self._result(
                    "provider_error",
                    reason_code=f"unexpected_{type(exc).__name__.lower()}",
                    summary=str(exc),
                    attempt_count=attempts,
                    transient=False,
                )

            try:
                decision = _parse_decision(turn.content)
            except ValueError as exc:
                return self._result(
                    "protocol_error",
                    reason_code="invalid_judge_output",
                    summary=str(exc),
                    attempt_count=attempts,
                    transient=False,
                )

            status = decision["status"]
            reason_code = decision["reason_code"]
            summary = decision["summary"]
            if status == "passed":
                if first_rejection is not None:
                    return self._result(
                        "inconclusive",
                        reason_code="judge_disagreement",
                        summary=(
                            "semantic judgments disagreed: first rejected "
                            f"({first_rejection[0]}), confirmation passed ({reason_code})"
                        ),
                        attempt_count=attempts,
                        transient=False,
                    )
                return self._result(
                    "passed",
                    reason_code=reason_code,
                    summary=summary,
                    attempt_count=attempts,
                    transient=False,
                )

            # Only passed/rejected are valid model decisions. A hard rejection
            # requires two semantic decisions that both rejected. A Provider retry
            # is not a semantic vote and cannot serve as confirmation.
            if first_rejection is None:
                first_rejection = (reason_code, summary)
                if attempts < self._policy.max_attempts:
                    continue
                return self._result(
                    "inconclusive",
                    reason_code="rejection_unconfirmed",
                    summary=(
                        "semantic rejection could not be independently confirmed "
                        "within the bounded attempt budget"
                    ),
                    attempt_count=attempts,
                    transient=False,
                )

            return self._result(
                "rejected",
                reason_code=reason_code,
                summary=summary,
                attempt_count=attempts,
                transient=False,
            )

        return self._result(  # pragma: no cover - loop always returns
            "inconclusive",
            reason_code="judge_attempts_exhausted",
            summary="semantic judge attempt budget exhausted",
            attempt_count=attempts,
            transient=False,
        )

    def _result(
        self,
        status: str,
        *,
        reason_code: str,
        summary: str,
        attempt_count: int,
        transient: bool,
    ) -> SemanticJudgeResult:
        return SemanticJudgeResult(
            status=status,
            reason_code=_bounded(reason_code, 120) or "unspecified",
            summary=_bounded(summary, 500),
            attempt_count=attempt_count,
            provider=_bounded(str(getattr(self._model, "provider", "")), 120) or None,
            model=_bounded(str(getattr(self._model, "model", "")), 200) or None,
            transient=transient,
        )


def _build_prompt(
    task: AgentTask,
    *,
    worker_summary: str,
    deterministic_result: VerificationResult | None,
    changed_files: list[str],
    unresolved_items: list[str],
) -> str:
    payload: dict[str, Any] = {
        "task_id": task.task_id,
        "objective": task.objective,
        "acceptance_criteria": list(task.acceptance_criteria),
        "worker_summary": _bounded(worker_summary, 12_000),
        "changed_files": list(changed_files)[:100],
        "unresolved_items": [_bounded(item, 500) for item in unresolved_items[:50]],
        "deterministic_verification": (
            deterministic_result.to_dict() if deterministic_result is not None else None
        ),
    }
    return "\n\n".join(
        [
            "[Identity]\nYou are PaperClaw's semantic acceptance judge.",
            (
                "[Rules]\nEvaluate only whether the Worker output satisfies the explicit "
                "objective and acceptance criteria. Use deterministic verification as immutable "
                "evidence: never upgrade failed checks, invent tool results, relax criteria, or "
                "infer success from confidence. Do not request tools or hidden reasoning."
            ),
            "[Task Evidence]\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True),
            (
                "[Output Contract]\nReturn exactly one JSON object with keys: "
                '{"status":"passed|rejected","reason_code":"short_code",'
                '"summary":"brief evidence-based explanation"}. '
                "Do not return markdown fences or additional text."
            ),
        ]
    )


def _parse_decision(content: str) -> dict[str, str]:
    raw = content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            raw = "\n".join(lines[1:-1]).strip()
            if raw.lower().startswith("json\n"):
                raw = raw[5:].lstrip()
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("semantic judge returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("semantic judge output must be a JSON object")
    status = data.get("status")
    reason_code = data.get("reason_code")
    summary = data.get("summary")
    if status not in {"passed", "rejected"}:
        raise ValueError("semantic judge status must be passed or rejected")
    if not isinstance(reason_code, str) or not reason_code.strip():
        raise ValueError("semantic judge reason_code must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("semantic judge summary must be a non-empty string")
    return {
        "status": status,
        "reason_code": _bounded(reason_code.strip(), 120),
        "summary": _bounded(summary.strip(), 500),
    }


def _bounded(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(0, limit - 3)] + "..."


__all__ = ["SemanticAcceptanceJudge", "SemanticJudgePolicy"]
